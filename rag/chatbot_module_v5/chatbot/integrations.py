"""공통 인증과 SQL 기반 학습·스테이지 관리 서비스."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatbot.concepts import STATUS_IN_PROGRESS, STATUS_NOT_STARTED, STATUS_PASSED
from chatbot.config import Settings
from chatbot.learning_management import (
    ConceptRow,
    LearningEventRow,
    QuizResultReceiptRow,
    QuizRetryRequestRow,
    StageRow,
    UserConceptProgressRow,
    UserStageProgressRow,
    create_database_engine,
    initialize_learning_management_schema,
)
from chatbot.schemas import GameEventOut
from chatbot.store import LearningContextRow, LearningSessionRow


class ConceptStatusError(Exception):
    """학습 상태 규칙을 지킬 수 없을 때."""


@dataclass(frozen=True)
class InProgressConcept:
    concept_id: str
    term: str
    term_full: str
    stage: str
    status: str


class ConceptStatusService(ABC):
    """RAG·퀴즈·게임이 사용하는 학습 관리 계약."""

    @abstractmethod
    def get_current_stage(self, user_id: str) -> str: ...

    @abstractmethod
    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]: ...

    @abstractmethod
    def get_concept_status(self, user_id: str, concept_id: str, stage_id: str) -> str: ...

    @abstractmethod
    def get_in_progress_concept(
        self, user_id: str, stage: str
    ) -> InProgressConcept | None: ...

    @abstractmethod
    def mark_in_progress(self, user_id: str, concept_id: str, stage: str) -> None: ...

    @abstractmethod
    def apply_quiz_result(
        self,
        *,
        user_id: str,
        submission_id: str,
        session_id: str,
        concept_id: str,
        stage_id: str,
        correct_count: int,
        passed: bool,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def get_unprocessed_events(self, *, limit: int = 100) -> list[GameEventOut]: ...

    @abstractmethod
    def mark_event_processed(self, event_id: str) -> GameEventOut: ...


class SqlConceptStatusService(ConceptStatusService):
    """CHAT_DB_URL에서 동작하는 실제 학습·스테이지 관리 구현."""

    def __init__(self, settings: Settings):
        self._engine = create_database_engine(settings.chat_db_url)
        initialize_learning_management_schema(
            self._engine,
            settings.stages_json_path,
            auto_create=settings.db_auto_create,
        )

    def close(self) -> None:
        self._engine.dispose()

    def get_current_stage(self, user_id: str) -> str:
        with Session(self._engine) as session:
            return self._current_stage(session, user_id)

    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
        with Session(self._engine) as session:
            concepts = self._stage_concepts(session, stage)
            rows = session.scalars(
                select(UserConceptProgressRow).where(
                    UserConceptProgressRow.user_id == user_id,
                    UserConceptProgressRow.stage_id == stage,
                )
            ).all()
            overlay = {row.concept_id: row.status for row in rows}
            return {
                concept.concept_id: overlay.get(concept.concept_id, STATUS_NOT_STARTED)
                for concept in concepts
            }

    def get_concept_status(
        self, user_id: str, concept_id: str, stage_id: str
    ) -> str:
        with Session(self._engine) as session:
            self._require_concept(session, concept_id, stage_id)
            row = session.get(
                UserConceptProgressRow, (user_id, concept_id, stage_id)
            )
            return row.status if row is not None else STATUS_NOT_STARTED

    def get_in_progress_concept(
        self, user_id: str, stage: str
    ) -> InProgressConcept | None:
        with Session(self._engine) as session:
            self._require_stage(session, stage)
            rows = session.execute(
                select(UserConceptProgressRow, ConceptRow)
                .join(
                    ConceptRow,
                    (ConceptRow.concept_id == UserConceptProgressRow.concept_id)
                    & (ConceptRow.stage_id == UserConceptProgressRow.stage_id),
                )
                .where(
                    UserConceptProgressRow.user_id == user_id,
                    UserConceptProgressRow.stage_id == stage,
                    UserConceptProgressRow.status == STATUS_IN_PROGRESS,
                )
            ).all()
            if not rows:
                return None
            if len(rows) > 1:
                raise ConceptStatusError(
                    "학습 중인 개념은 사용자당 하나만 있을 수 있습니다."
                )
            progress, concept = rows[0]
            return InProgressConcept(
                concept_id=concept.concept_id,
                term=concept.term,
                term_full=concept.term,
                stage=concept.stage_id,
                status=progress.status,
            )

    def mark_in_progress(self, user_id: str, concept_id: str, stage: str) -> None:
        now = datetime.now(timezone.utc)
        with Session(self._engine) as session:
            if stage != self._current_stage(session, user_id):
                raise ConceptStatusError("현재 스테이지의 개념만 학습할 수 있습니다.")
            self._require_concept(session, concept_id, stage)
            existing = session.get(
                UserConceptProgressRow, (user_id, concept_id, stage)
            )
            if existing is not None and existing.status == STATUS_PASSED:
                raise ConceptStatusError("통과한 개념은 학습 중으로 바꿀 수 없습니다.")
            if existing is not None and existing.status == STATUS_IN_PROGRESS:
                return
            stage_progress = session.get(UserStageProgressRow, (user_id, stage))
            if stage_progress is None:
                session.add(
                    UserStageProgressRow(
                        user_id=user_id,
                        stage_id=stage,
                        status="in_progress",
                        started_at=now,
                        completed_at=None,
                    )
                )
            if existing is None:
                session.add(
                    UserConceptProgressRow(
                        user_id=user_id,
                        concept_id=concept_id,
                        stage_id=stage,
                        status=STATUS_IN_PROGRESS,
                        started_at=now,
                        first_passed_at=None,
                        updated_at=now,
                    )
                )
            else:
                existing.status = STATUS_IN_PROGRESS
                existing.started_at = existing.started_at or now
                existing.updated_at = now
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ConceptStatusError(
                    "다른 요청에서 이미 학습을 시작했습니다. 현재 학습 상태를 다시 확인해 주세요."
                ) from exc

    def apply_quiz_result(
        self,
        *,
        user_id: str,
        submission_id: str,
        session_id: str,
        concept_id: str,
        stage_id: str,
        correct_count: int,
        passed: bool,
    ) -> dict[str, Any]:
        if not submission_id.strip():
            raise ConceptStatusError("submission_id가 필요합니다.")
        if not 0 <= correct_count <= 3:
            raise ConceptStatusError("correct_count는 0부터 3 사이여야 합니다.")
        now = datetime.now(timezone.utc)
        with Session(self._engine) as session:
            receipt = session.get(QuizResultReceiptRow, submission_id)
            if receipt is not None:
                if receipt.user_id != user_id:
                    raise ConceptStatusError("퀴즈 결과를 찾을 수 없습니다.")
                return dict(receipt.result_payload)

            session_row = session.get(LearningSessionRow, session_id)
            context = session.get(LearningContextRow, session_id)
            if session_row is None or session_row.user_id != user_id:
                raise ConceptStatusError("학습 세션을 찾을 수 없습니다.")
            if session_row.status != "completed":
                raise ConceptStatusError(
                    "완료된 학습 세션에만 퀴즈 결과를 기록할 수 있습니다."
                )
            if context is None or context.user_id != user_id:
                raise ConceptStatusError("학습 맥락을 찾을 수 없습니다.")
            if session_row.concept_id != concept_id or session_row.stage_id != stage_id:
                raise ConceptStatusError(
                    "퀴즈 결과의 개념 또는 스테이지가 학습 세션과 다릅니다."
                )
            if context.quiz_status != "pending":
                raise ConceptStatusError("이미 퀴즈 결과가 기록된 학습 세션입니다.")

            progress = session.get(
                UserConceptProgressRow, (user_id, concept_id, stage_id)
            )
            if progress is None or progress.status != STATUS_IN_PROGRESS:
                raise ConceptStatusError(
                    "현재 학습 중인 개념 상태와 퀴즈 결과가 맞지 않습니다."
                )

            event_ids: list[str] = []
            next_stage_id: str | None = None
            stage_completed = False
            context.quiz_status = "passed" if passed else "failed"
            if passed:
                progress.status = STATUS_PASSED
                progress.first_passed_at = progress.first_passed_at or now
                progress.updated_at = now
                session.flush()
                passed_count, total_count = self._stage_counts(
                    session, user_id, stage_id
                )
                stage_completed = passed_count == total_count
                concept_event_id = str(uuid.uuid4())
                concept_payload = {
                    "event_id": concept_event_id,
                    "event_type": "concept_passed",
                    "user_id": user_id,
                    "stage_id": stage_id,
                    "concept_id": concept_id,
                    "first_pass": True,
                    "passed_count": passed_count,
                    "total_count": total_count,
                    "stage_completed": stage_completed,
                    "occurred_at": _iso_utc(now),
                }
                session.add(
                    LearningEventRow(
                        event_id=concept_event_id,
                        event_type="concept_passed",
                        user_id=user_id,
                        payload=concept_payload,
                        occurred_at=now,
                        processed_at=None,
                    )
                )
                event_ids.append(concept_event_id)
                if stage_completed:
                    next_stage_id = self._complete_stage(
                        session, user_id, stage_id, now
                    )
                    stage_event_id = str(uuid.uuid4())
                    stage_payload = {
                        "event_id": stage_event_id,
                        "event_type": "stage_completed",
                        "user_id": user_id,
                        "stage_id": stage_id,
                        "passed_count": passed_count,
                        "total_count": total_count,
                        "next_stage_id": next_stage_id,
                        "occurred_at": _iso_utc(now),
                    }
                    session.add(
                        LearningEventRow(
                            event_id=stage_event_id,
                            event_type="stage_completed",
                            user_id=user_id,
                            payload=stage_payload,
                            occurred_at=now,
                            processed_at=None,
                        )
                    )
                    event_ids.append(stage_event_id)
            else:
                passed_count, total_count = self._stage_counts(
                    session, user_id, stage_id
                )

            result = {
                "submission_id": submission_id,
                "session_id": session_id,
                "concept_id": concept_id,
                "stage_id": stage_id,
                "correct_count": correct_count,
                "passed": passed,
                "concept_status": STATUS_PASSED if passed else STATUS_IN_PROGRESS,
                "quiz_status": "passed" if passed else "failed",
                "passed_count": passed_count,
                "total_count": total_count,
                "stage_completed": stage_completed,
                "next_stage_id": next_stage_id,
                "event_ids": event_ids,
            }
            session.add(
                QuizResultReceiptRow(
                    submission_id=submission_id,
                    user_id=user_id,
                    session_id=session_id,
                    concept_id=concept_id,
                    stage_id=stage_id,
                    result_payload=result,
                    created_at=now,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                replay = session.get(QuizResultReceiptRow, submission_id)
                if replay is not None and replay.user_id == user_id:
                    return dict(replay.result_payload)
                raise ConceptStatusError("퀴즈 결과를 저장하지 못했습니다.") from exc
            return result

    def get_unprocessed_events(self, *, limit: int = 100) -> list[GameEventOut]:
        if limit < 1:
            raise ConceptStatusError("limit은 1 이상이어야 합니다.")
        with Session(self._engine) as session:
            rows = session.scalars(
                select(LearningEventRow)
                .where(LearningEventRow.processed_at.is_(None))
                .order_by(
                    LearningEventRow.occurred_at,
                    case(
                        (LearningEventRow.event_type == "concept_passed", 0),
                        else_=1,
                    ),
                    LearningEventRow.event_id,
                )
                .limit(limit)
            ).all()
            return [_event(row) for row in rows]

    def mark_event_processed(self, event_id: str) -> GameEventOut:
        with Session(self._engine) as session:
            row = session.get(LearningEventRow, event_id)
            if row is None:
                raise ConceptStatusError("학습 이벤트를 찾을 수 없습니다.")
            if row.processed_at is None:
                row.processed_at = datetime.now(timezone.utc)
                session.commit()
                session.refresh(row)
            return _event(row)

    def set_current_stage(self, user_id: str, stage: str) -> None:
        """개발 도구: 지정 단계보다 앞선 단계를 모두 통과시킨다."""
        with Session(self._engine) as session:
            stage_ids = self._ordered_stage_ids(session)
            if stage not in stage_ids:
                raise ConceptStatusError(f"알 수 없는 스테이지입니다: {stage}")
            for stage_id in stage_ids[: stage_ids.index(stage)]:
                self._pass_stage_in_session(session, user_id, stage_id)
            if session.get(UserStageProgressRow, (user_id, stage)) is None:
                session.add(
                    UserStageProgressRow(
                        user_id=user_id,
                        stage_id=stage,
                        status="in_progress",
                        started_at=datetime.now(timezone.utc),
                        completed_at=None,
                    )
                )
            session.commit()

    def pass_stage(self, user_id: str, stage: str) -> None:
        """개발 도구: 현재 단계 전체를 passed로 만든다."""
        with Session(self._engine) as session:
            if stage != self._current_stage(session, user_id):
                raise ConceptStatusError("현재 스테이지만 전체 통과 처리할 수 있습니다.")
            self._pass_stage_in_session(session, user_id, stage)
            session.commit()

    def reset_user(self, user_id: str) -> None:
        with Session(self._engine) as session:
            session.execute(
                delete(QuizRetryRequestRow).where(
                    QuizRetryRequestRow.user_id == user_id
                )
            )
            session.execute(
                delete(QuizResultReceiptRow).where(
                    QuizResultReceiptRow.user_id == user_id
                )
            )
            session.execute(
                delete(LearningEventRow).where(LearningEventRow.user_id == user_id)
            )
            session.execute(
                delete(UserConceptProgressRow).where(
                    UserConceptProgressRow.user_id == user_id
                )
            )
            session.execute(
                delete(UserStageProgressRow).where(
                    UserStageProgressRow.user_id == user_id
                )
            )
            session.commit()

    def get_quiz_retry_request(
        self, user_id: str, original_session_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        with Session(self._engine) as session:
            row = session.scalars(
                select(QuizRetryRequestRow).where(
                    QuizRetryRequestRow.user_id == user_id,
                    QuizRetryRequestRow.idempotency_key == idempotency_key,
                )
            ).one_or_none()
            if row is None:
                return None
            if row.original_session_id != original_session_id:
                raise ConceptStatusError(
                    "같은 Idempotency-Key를 다른 퀴즈 재요청에 사용할 수 없습니다."
                )
            return dict(row.response_payload)

    def save_quiz_retry_request(
        self,
        *,
        user_id: str,
        original_session_id: str,
        retry_session_id: str,
        idempotency_key: str,
        response_payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with Session(self._engine) as session:
            existing = session.scalars(
                select(QuizRetryRequestRow).where(
                    QuizRetryRequestRow.user_id == user_id,
                    QuizRetryRequestRow.idempotency_key == idempotency_key,
                )
            ).one_or_none()
            if existing is not None:
                if existing.original_session_id != original_session_id:
                    raise ConceptStatusError(
                        "같은 Idempotency-Key를 다른 퀴즈 재요청에 사용할 수 없습니다."
                    )
                return dict(existing.response_payload)
            session.add(
                QuizRetryRequestRow(
                    request_id=str(uuid.uuid4()),
                    user_id=user_id,
                    original_session_id=original_session_id,
                    retry_session_id=retry_session_id,
                    idempotency_key=idempotency_key,
                    response_payload=response_payload,
                    created_at=now,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                replay = session.scalars(
                    select(QuizRetryRequestRow).where(
                        QuizRetryRequestRow.user_id == user_id,
                        QuizRetryRequestRow.idempotency_key == idempotency_key,
                    )
                ).one_or_none()
                if replay is not None and replay.original_session_id == original_session_id:
                    return dict(replay.response_payload)
                raise ConceptStatusError("퀴즈 재요청 결과를 저장하지 못했습니다.") from exc
            return response_payload

    def _current_stage(self, session: Session, user_id: str) -> str:
        stage_ids = self._ordered_stage_ids(session)
        for stage_id in stage_ids[:-1]:
            passed, total = self._stage_counts(session, user_id, stage_id)
            if total == 0 or passed < total:
                return stage_id
        return stage_ids[-1]

    def _ordered_stage_ids(self, session: Session) -> list[str]:
        stage_ids = list(
            session.scalars(select(StageRow.stage_id).order_by(StageRow.display_order))
        )
        if not stage_ids:
            raise ConceptStatusError("스테이지 카탈로그가 비어 있습니다.")
        return stage_ids

    def _stage_concepts(self, session: Session, stage: str) -> list[ConceptRow]:
        self._require_stage(session, stage)
        return list(
            session.scalars(
                select(ConceptRow)
                .where(ConceptRow.stage_id == stage)
                .order_by(ConceptRow.display_order)
            )
        )

    def _require_stage(self, session: Session, stage: str) -> StageRow:
        row = session.get(StageRow, stage)
        if row is None:
            raise ConceptStatusError(f"알 수 없는 스테이지입니다: {stage}")
        return row

    def _require_concept(
        self, session: Session, concept_id: str, stage_id: str
    ) -> ConceptRow:
        row = session.get(ConceptRow, (concept_id, stage_id))
        if row is None:
            raise ConceptStatusError(
                f"스테이지 {stage_id}에서 개념을 찾을 수 없습니다: {concept_id}"
            )
        return row

    def _stage_counts(
        self, session: Session, user_id: str, stage_id: str
    ) -> tuple[int, int]:
        total = int(
            session.scalar(
                select(func.count()).select_from(ConceptRow).where(
                    ConceptRow.stage_id == stage_id
                )
            )
            or 0
        )
        passed = int(
            session.scalar(
                select(func.count()).select_from(UserConceptProgressRow).where(
                    UserConceptProgressRow.user_id == user_id,
                    UserConceptProgressRow.stage_id == stage_id,
                    UserConceptProgressRow.status == STATUS_PASSED,
                )
            )
            or 0
        )
        return passed, total

    def _complete_stage(
        self,
        session: Session,
        user_id: str,
        stage_id: str,
        now: datetime,
    ) -> str | None:
        stage_ids = self._ordered_stage_ids(session)
        index = stage_ids.index(stage_id)
        progress = session.get(UserStageProgressRow, (user_id, stage_id))
        if progress is None:
            progress = UserStageProgressRow(
                user_id=user_id,
                stage_id=stage_id,
                status="completed",
                started_at=now,
                completed_at=now,
            )
            session.add(progress)
        else:
            progress.status = "completed"
            progress.completed_at = progress.completed_at or now
        next_stage_id = stage_ids[index + 1] if index + 1 < len(stage_ids) else None
        if next_stage_id is not None:
            next_progress = session.get(
                UserStageProgressRow, (user_id, next_stage_id)
            )
            if next_progress is None:
                session.add(
                    UserStageProgressRow(
                        user_id=user_id,
                        stage_id=next_stage_id,
                        status="in_progress",
                        started_at=now,
                        completed_at=None,
                    )
                )
        return next_stage_id

    def _pass_stage_in_session(
        self, session: Session, user_id: str, stage_id: str
    ) -> None:
        now = datetime.now(timezone.utc)
        for concept in self._stage_concepts(session, stage_id):
            row = session.get(
                UserConceptProgressRow,
                (user_id, concept.concept_id, stage_id),
            )
            if row is None:
                session.add(
                    UserConceptProgressRow(
                        user_id=user_id,
                        concept_id=concept.concept_id,
                        stage_id=stage_id,
                        status=STATUS_PASSED,
                        started_at=now,
                        first_passed_at=now,
                        updated_at=now,
                    )
                )
            else:
                row.status = STATUS_PASSED
                row.started_at = row.started_at or now
                row.first_passed_at = row.first_passed_at or now
                row.updated_at = now
        self._complete_stage(session, user_id, stage_id, now)


def get_concept_status(
    service: ConceptStatusService,
    user_id: str,
    concept_id: str,
    stage_id: str,
) -> str:
    """퀴즈 등 다른 모듈이 진행 테이블 대신 사용하는 공개 조회 함수."""
    return service.get_concept_status(user_id, concept_id, stage_id)


def get_unprocessed_events(
    service: ConceptStatusService, *, limit: int = 100
) -> list[GameEventOut]:
    """게임 모듈이 아직 처리하지 않은 학습 이벤트를 조회한다."""
    return service.get_unprocessed_events(limit=limit)


def mark_event_processed(
    service: ConceptStatusService, event_id: str
) -> GameEventOut:
    """게임 모듈이 처리 완료한 이벤트를 멱등하게 표시한다."""
    return service.mark_event_processed(event_id)


def _event(row: LearningEventRow) -> GameEventOut:
    payload = dict(row.payload)
    return GameEventOut(
        event_id=row.event_id,
        event_type=row.event_type,  # type: ignore[arg-type]
        user_id=row.user_id,
        stage_id=payload["stage_id"],
        concept_id=payload.get("concept_id"),
        first_pass=payload.get("first_pass"),
        passed_count=int(payload["passed_count"]),
        total_count=int(payload["total_count"]),
        stage_completed=bool(
            payload.get("stage_completed", row.event_type == "stage_completed")
        ),
        next_stage_id=payload.get("next_stage_id"),
        occurred_at=_as_utc(row.occurred_at),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def get_current_user_id(x_user_id: Annotated[str | None, Header()] = None) -> str:
    """개발용 인증. 통합 시 공통 인증 의존성으로 이 함수만 교체한다."""

    if x_user_id is None or not x_user_id.strip():
        raise HTTPException(status_code=401, detail="X-User-Id 헤더가 필요합니다.")
    return x_user_id.strip()


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
