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
from sqlalchemy import DateTime, Index, String, create_engine, delete, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from chatbot.concepts import (
    STATUS_IN_PROGRESS,
    STATUS_PASSED,
    STATUS_NOT_STARTED,
    ConceptRef,
    StageCatalog,
    StageRef,
    load_stage_catalog,
)
from chatbot.config import Settings


class ConceptStatusError(Exception):
    """개념 상태 규칙을 지킬 수 없을 때."""


@dataclass(frozen=True)
class InProgressConcept:
    concept_id: str
    term: str
    term_full: str
    stage: str
    status: str


class ConceptStatusService(ABC):
    """학습 관리 모듈이 나중에 구현체를 교체한다."""

    def get_current_stage(self, user_id: str) -> str:
        """not_started·in_progress가 남은 가장 낮은 스테이지를 계산한다.

        Stage 1~4가 모두 통과되면 Stage 5이며, Stage 5까지 모두 통과해도
        완료 상태를 나타내기 위해 Stage 5를 유지한다.
        """
        for stage in ("stage1", "stage2", "stage3", "stage4"):
            statuses = self.get_statuses(user_id, stage)
            if not statuses or any(status != STATUS_PASSED for status in statuses.values()):
                return stage
        return "stage5"

    @abstractmethod
    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
        """스테이지 개념 순서의 concept_id → 상태. 기록이 없으면 not_started."""

    @abstractmethod
    def get_in_progress_concept(self, user_id: str, stage: str) -> InProgressConcept | None:
        """해당 스테이지의 in_progress 개념. 사용자당 0개 또는 1개."""

    @abstractmethod
    def mark_in_progress(self, user_id: str, concept_id: str, stage: str) -> None:
        """(concept_id, stage)의 not_started를 in_progress로 바꾼다."""

    def note_quiz_result(self, user_id: str, concept_id: str, stage: str, passed: bool) -> None:
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
    concept_id: Mapped[str] = mapped_column(String, primary_key=True)
    stage_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index(
            "uq_dev_concept_status_one_in_progress",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'in_progress'"),
            postgresql_where=text("status = 'in_progress'"),
        ),
    )


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
        if settings.chat_db_url.startswith("sqlite"):
            self._migrate_sqlite_status_schema()
        self._drop_legacy_user_stage_table()
        Base.metadata.create_all(self._engine)
        if settings.chat_db_url.startswith("sqlite"):
            with self._engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_dev_concept_status_one_in_progress "
                    "ON dev_concept_status (user_id) WHERE status = 'in_progress'"
                )

    def close(self) -> None:
        self._engine.dispose()

    def set_current_stage(self, user_id: str, stage: str) -> None:
        """개발·테스트용으로 지정 스테이지보다 앞선 스테이지를 통과 처리한다."""
        self._require_stage(stage)
        ordered = ("stage1", "stage2", "stage3", "stage4", "stage5")
        self._pass_stages(user_id, ordered[: ordered.index(stage)])

    def pass_stage(self, user_id: str, stage: str) -> None:
        """개발 도구용으로 한 스테이지의 모든 개념을 통과 처리한다."""
        self._require_stage(stage)
        self._pass_stages(user_id, (stage,))

    def reset_user(self, user_id: str) -> None:
        """개발 도구용으로 한 사용자의 로컬 개념 상태를 지운다."""
        with Session(self._engine) as session:
            session.execute(
                delete(DevConceptStatusRow).where(DevConceptStatusRow.user_id == user_id)
            )
            session.commit()

    def _pass_stages(self, user_id: str, stages: tuple[str, ...]) -> None:
        if not stages:
            return
        now = datetime.now(timezone.utc)
        with Session(self._engine) as session:
            for stage in stages:
                stage_ref = self._require_stage(stage)
                for concept in stage_ref.concepts:
                    key = (user_id, concept.concept_id, stage)
                    row = session.get(DevConceptStatusRow, key)
                    if row is None:
                        session.add(
                            DevConceptStatusRow(
                                user_id=user_id,
                                concept_id=concept.concept_id,
                                stage_id=stage,
                                status=STATUS_PASSED,
                                updated_at=now,
                            )
                        )
                    else:
                        row.status = STATUS_PASSED
                        row.updated_at = now
            session.commit()

    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
        stage_ref = self._require_stage(stage)
        with Session(self._engine) as session:
            rows = session.scalars(
                select(DevConceptStatusRow).where(
                    DevConceptStatusRow.user_id == user_id,
                    DevConceptStatusRow.stage_id == stage,
                )
            ).all()
            overlay = {row.concept_id: row.status for row in rows}
        return {concept.concept_id: overlay.get(concept.concept_id, STATUS_NOT_STARTED) for concept in stage_ref.concepts}

    def get_in_progress_concept(self, user_id: str, stage: str) -> InProgressConcept | None:
        self._require_stage(stage)
        with Session(self._engine) as session:
            rows = session.scalars(
                select(DevConceptStatusRow).where(
                    DevConceptStatusRow.user_id == user_id,
                    DevConceptStatusRow.stage_id == stage,
                    DevConceptStatusRow.status == STATUS_IN_PROGRESS,
                )
            ).all()
            found = [(row.concept_id, row.stage_id) for row in rows]
        if not found:
            return None
        if len(found) > 1:
            raise ConceptStatusError("학습 중인 개념은 사용자당 하나만 있을 수 있습니다.")
        concept_id, stage_id = found[0]
        concept = self._concept_in_stage(concept_id, stage_id)
        return InProgressConcept(
            concept_id=concept.concept_id,
            term=concept.term,
            term_full=concept.term_full,
            stage=concept.stage_id,
            status=STATUS_IN_PROGRESS,
        )

    def mark_in_progress(self, user_id: str, concept_id: str, stage: str) -> None:
        concept = self._require_for_learning(user_id, concept_id, stage)
        with Session(self._engine) as session:
            in_progress_rows = session.scalars(
                select(DevConceptStatusRow).where(
                    DevConceptStatusRow.user_id == user_id,
                    DevConceptStatusRow.stage_id == stage,
                    DevConceptStatusRow.status == STATUS_IN_PROGRESS,
                )
            ).all()
            if any(row.concept_id != concept_id for row in in_progress_rows):
                raise ConceptStatusError("학습 중인 개념은 사용자당 하나만 있을 수 있습니다.")
            row = session.get(DevConceptStatusRow, (user_id, concept_id, stage))
            if row is not None and row.status == STATUS_PASSED:
                raise ConceptStatusError("통과한 개념은 학습 중으로 바꿀 수 없습니다.")
            if row is not None and row.status == STATUS_IN_PROGRESS:
                return
            now = datetime.now(timezone.utc)
            if row is None:
                session.add(
                    DevConceptStatusRow(
                        user_id=user_id,
                        concept_id=concept_id,
                        stage_id=concept.stage_id,
                        status=STATUS_IN_PROGRESS,
                        updated_at=now,
                    )
                )
            else:
                row.stage_id = concept.stage_id
                row.status = STATUS_IN_PROGRESS
                row.updated_at = now
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ConceptStatusError(
                    "다른 요청에서 이미 학습을 시작했습니다. 현재 학습 상태를 다시 확인해 주세요."
                ) from exc

    def note_quiz_result(self, user_id: str, concept_id: str, stage: str, passed: bool) -> None:
        """설정이 켜져 있고 통과 보고일 때만 in_progress 개념을 passed로 바꾼다."""
        if not self._simulate_quiz_status or not passed:
            return
        with Session(self._engine) as session:
            row = session.get(DevConceptStatusRow, (user_id, concept_id, stage))
            if row is None or row.status != STATUS_IN_PROGRESS:
                return
            row.status = STATUS_PASSED
            row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def _require_stage(self, stage_id: str) -> StageRef:
        stage = self._catalog.stages.get(stage_id)
        if stage is None:
            raise ConceptStatusError(f"알 수 없는 스테이지입니다: {stage_id}")
        return stage

    def _concept_in_stage(self, concept_id: str, stage_id: str) -> ConceptRef:
        for concept in self._catalog.by_concept.get(concept_id, ()):
            if concept.stage_id == stage_id:
                return concept
        raise ConceptStatusError(f"스테이지 {stage_id}에서 개념을 찾을 수 없습니다: {concept_id}")

    def _require_for_learning(self, user_id: str, concept_id: str, stage: str) -> ConceptRef:
        if concept_id not in self._catalog.by_concept:
            raise ConceptStatusError(f"학습 개념이 아닙니다: {concept_id}")
        self._require_stage(stage)
        if stage != self.get_current_stage(user_id):
            raise ConceptStatusError("현재 스테이지의 개념만 학습할 수 있습니다.")
        return self._concept_in_stage(concept_id, stage)

    def _migrate_sqlite_status_schema(self) -> None:
        """기존 concept ID 컬럼과 한글 상태값을 보존 전환한다."""
        inspector = inspect(self._engine)
        if "dev_concept_status" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("dev_concept_status")}
        primary_key = set(
            inspector.get_pk_constraint("dev_concept_status").get("constrained_columns") or []
        )
        target_key = {"user_id", "concept_id", "stage_id"}
        if "concept_id" in columns and primary_key == target_key:
            with self._engine.begin() as connection:
                connection.exec_driver_sql(
                    "UPDATE dev_concept_status SET status = CASE status "
                    "WHEN '미학습' THEN 'not_started' "
                    "WHEN '미통과' THEN 'in_progress' "
                    "WHEN 'failed' THEN 'in_progress' "
                    "WHEN '통과' THEN 'passed' ELSE status END"
                )
            return
        legacy_id = "doc_id" if "doc_id" in columns else "concept_id"
        valid_legacy_keys = (
            {"user_id", legacy_id},
            {"user_id", legacy_id, "stage_id"},
        )
        if primary_key not in valid_legacy_keys or "stage_id" not in columns:
            raise ConceptStatusError("dev_concept_status 기본키 구조를 자동 변환할 수 없습니다.")
        with self._engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE dev_concept_status RENAME TO dev_concept_status_legacy"
            )
            DevConceptStatusRow.__table__.create(connection)
            connection.exec_driver_sql(
                "INSERT INTO dev_concept_status "
                "(user_id, concept_id, stage_id, status, updated_at) "
                f"SELECT user_id, {legacy_id}, stage_id, CASE status "
                "WHEN '미학습' THEN 'not_started' "
                "WHEN '미통과' THEN 'in_progress' "
                "WHEN 'failed' THEN 'in_progress' "
                "WHEN '통과' THEN 'passed' ELSE status END, updated_at "
                "FROM dev_concept_status_legacy"
            )
            connection.exec_driver_sql("DROP TABLE dev_concept_status_legacy")

    def _drop_legacy_user_stage_table(self) -> None:
        """현재 스테이지 저장을 폐기했으므로 기존 개발 테이블도 제거한다."""
        if "dev_user_stage" not in inspect(self._engine).get_table_names():
            return
        with self._engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE dev_user_stage")


def get_current_user_id(x_user_id: Annotated[str | None, Header()] = None) -> str:
    """개발용 인증. 통합 시 공통 인증 의존성으로 이 함수만 교체한다."""
    if x_user_id is None or not x_user_id.strip():
        raise HTTPException(status_code=401, detail="X-User-Id 헤더가 필요합니다.")
    return x_user_id.strip()


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
