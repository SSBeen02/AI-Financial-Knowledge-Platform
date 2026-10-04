"""인증 의존성과 개념 상태 인터페이스.

서비스는 개념 상태를 직접 갱신하지 않는다. 퀴즈 결과를 받을 때는
`note_quiz_result()`만 호출한다. 통과 상태 시뮬레이트는 개발용 SQLite 구현이
`DEV_USE_LOCAL_STATUS`로 활성화되고 `DEV_SIMULATE_QUIZ_STATUS`도 켜져 있을 때만 수행한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from chatbot.concepts import (
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_UNLEARNED,
    ConceptRef,
    StageCatalog,
    StageRef,
    load_stage_catalog,
)
from chatbot.config import Settings


class ConceptStatusError(Exception):
    """개념 상태 규칙을 지킬 수 없을 때."""


@dataclass(frozen=True)
class FailedConcept:
    doc_id: str
    term: str
    term_full: str
    stage: str
    status: str


class ConceptStatusService(ABC):
    """학습 관리 모듈이 나중에 구현체를 교체한다."""

    @abstractmethod
    def get_current_stage(self, user_id: str) -> str:
        """사용자의 현재 스테이지 id. 기록이 없으면 stage1."""

    @abstractmethod
    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
        """스테이지 개념 순서의 doc_id → 상태. 기록이 없으면 미학습."""

    @abstractmethod
    def get_failed_concept(self, user_id: str) -> FailedConcept | None:
        """미통과 개념. 사용자당 0개 또는 1개."""

    @abstractmethod
    def mark_failed(self, user_id: str, doc_id: str, stage: str | None = None) -> None:
        """미학습을 미통과로 바꾼다. stage는 명시적 Stage 5 선택에만 사용한다."""

    def note_quiz_result(self, user_id: str, doc_id: str, passed: bool) -> None:
        """퀴즈 결과를 개념 상태에 반영하지 않는다.

        `report_quiz_result()`는 quiz_status만 저장한 뒤 이 메서드를 호출한다.
        개발용 구현만 설정이 켜진 경우 통과를 기록한다.
        """
        return None


class Base(DeclarativeBase):
    pass


class DevConceptStatusRow(Base):
    __tablename__ = "dev_concept_status"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    stage_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DevUserStageRow(Base):
    __tablename__ = "dev_user_stage"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    stage_id: Mapped[str] = mapped_column(String, nullable=False)


class DevConceptStatusService(ConceptStatusService):
    """통합 전 개념 상태. 명시적으로 켠 개발 환경에서만 테이블을 만든다."""

    def __init__(self, settings: Settings):
        if not settings.dev_use_local_status:
            raise ConceptStatusError(
                "개발용 개념 상태를 사용하려면 DEV_USE_LOCAL_STATUS=true로 설정해야 합니다. "
                "배포에서는 실제 ConceptStatusService 구현을 주입하세요."
            )
        self._simulate_quiz_status = settings.dev_simulate_quiz_status
        self._catalog: StageCatalog = load_stage_catalog(settings.stages_json_path)
        connect_args = {}
        if settings.chat_db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        self._engine = create_engine(settings.chat_db_url, connect_args=connect_args)
        Base.metadata.create_all(self._engine)

    def close(self) -> None:
        self._engine.dispose()

    def get_current_stage(self, user_id: str) -> str:
        with Session(self._engine) as session:
            row = session.get(DevUserStageRow, user_id)
            stage_id = row.stage_id if row is not None else "stage1"
        self._require_stage(stage_id)
        return stage_id

    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
        stage_ref = self._require_stage(stage)
        with Session(self._engine) as session:
            rows = session.scalars(
                select(DevConceptStatusRow).where(DevConceptStatusRow.user_id == user_id)
            ).all()
            overlay = {row.doc_id: row.status for row in rows}
        return {concept.doc_id: overlay.get(concept.doc_id, STATUS_UNLEARNED) for concept in stage_ref.concepts}

    def get_failed_concept(self, user_id: str) -> FailedConcept | None:
        with Session(self._engine) as session:
            rows = session.scalars(
                select(DevConceptStatusRow).where(
                    DevConceptStatusRow.user_id == user_id,
                    DevConceptStatusRow.status == STATUS_FAILED,
                )
            ).all()
            found = [(row.doc_id, row.stage_id) for row in rows]
        if not found:
            return None
        if len(found) > 1:
            raise ConceptStatusError("미통과 개념은 사용자당 하나만 있을 수 있습니다.")
        doc_id, stage_id = found[0]
        concept = self._concept_in_stage(doc_id, stage_id)
        return FailedConcept(
            doc_id=concept.doc_id,
            term=concept.term,
            term_full=concept.term_full,
            stage=concept.stage_id,
            status=STATUS_FAILED,
        )

    def mark_failed(self, user_id: str, doc_id: str, stage: str | None = None) -> None:
        concept = self._require_for_learning(user_id, doc_id, stage)
        with Session(self._engine) as session:
            failed_rows = session.scalars(
                select(DevConceptStatusRow).where(
                    DevConceptStatusRow.user_id == user_id,
                    DevConceptStatusRow.status == STATUS_FAILED,
                )
            ).all()
            if any(row.doc_id != doc_id for row in failed_rows):
                raise ConceptStatusError("미통과 개념은 사용자당 하나만 있을 수 있습니다.")
            row = session.get(DevConceptStatusRow, (user_id, doc_id))
            if row is not None and row.status == STATUS_PASSED:
                raise ConceptStatusError("통과한 개념은 미통과로 바꿀 수 없습니다.")
            if row is not None and row.status == STATUS_FAILED:
                return
            now = datetime.now(timezone.utc)
            if row is None:
                session.add(
                    DevConceptStatusRow(
                        user_id=user_id,
                        doc_id=doc_id,
                        stage_id=concept.stage_id,
                        status=STATUS_FAILED,
                        updated_at=now,
                    )
                )
            else:
                row.stage_id = concept.stage_id
                row.status = STATUS_FAILED
                row.updated_at = now
            session.commit()

    def note_quiz_result(self, user_id: str, doc_id: str, passed: bool) -> None:
        """설정이 켜져 있고 통과 보고일 때만 미통과 개념을 통과로 바꾼다."""
        if not self._simulate_quiz_status or not passed:
            return
        with Session(self._engine) as session:
            row = session.get(DevConceptStatusRow, (user_id, doc_id))
            if row is None or row.status != STATUS_FAILED:
                return
            row.status = STATUS_PASSED
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def _require_stage(self, stage_id: str) -> StageRef:
        stage = self._catalog.stages.get(stage_id)
        if stage is None:
            raise ConceptStatusError(f"알 수 없는 스테이지입니다: {stage_id}")
        return stage

    def _concept_in_stage(self, doc_id: str, stage_id: str) -> ConceptRef:
        for concept in self._catalog.by_doc.get(doc_id, ()):
            if concept.stage_id == stage_id:
                return concept
        raise ConceptStatusError(f"스테이지 {stage_id}에서 개념을 찾을 수 없습니다: {doc_id}")

    def _require_for_learning(self, user_id: str, doc_id: str, stage: str | None) -> ConceptRef:
        if doc_id not in self._catalog.by_doc:
            raise ConceptStatusError(f"학습 개념이 아닙니다: {doc_id}")
        if stage is None:
            stage_id = self.get_current_stage(user_id)
        elif stage == "stage5":
            stage_id = stage
        else:
            raise ConceptStatusError("명시적으로 선택할 수 있는 스테이지는 stage5뿐입니다.")
        return self._concept_in_stage(doc_id, stage_id)


def get_current_user_id(x_user_id: Annotated[str | None, Header()] = None) -> str:
    """개발용 인증. 통합 시 공통 인증 의존성으로 이 함수만 교체한다."""
    if x_user_id is None or not x_user_id.strip():
        raise HTTPException(status_code=401, detail="X-User-Id 헤더가 필요합니다.")
    return x_user_id.strip()


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
