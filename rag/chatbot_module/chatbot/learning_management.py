"""학습·스테이지 관리 영속 모델과 카탈로그 시드.

SQLite와 PostgreSQL에서 같은 SQLAlchemy 모델을 사용한다. 다른 모듈은 이 테이블을
직접 읽지 않고 ``ConceptStatusService`` 및 공개 함수 계약을 사용한다.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


CONCEPT_STATUSES = {"not_started", "in_progress", "passed"}
STAGE_STATUSES = {"in_progress", "completed"}
EVENT_TYPES = {"concept_passed", "stage_completed"}
LEARNING_MANAGEMENT_TABLES = {
    "stages",
    "concepts",
    "user_concept_progress",
    "user_stage_progress",
    "learning_events",
    "quiz_result_receipts",
    "quiz_retry_requests",
}


class DatabaseSchemaNotReadyError(RuntimeError):
    """DB_AUTO_CREATE=false인 서버에 migration/seed가 준비되지 않은 경우."""


def _json_type() -> JSON:
    return JSON().with_variant(JSONB(), "postgresql")


class LearningManagementBase(DeclarativeBase):
    pass


class StageRow(LearningManagementBase):
    __tablename__ = "stages"

    stage_id: Mapped[str] = mapped_column(String, primary_key=True)
    name_ko: Mapped[str] = mapped_column(String, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ConceptRow(LearningManagementBase):
    __tablename__ = "concepts"

    concept_id: Mapped[str] = mapped_column(String, primary_key=True)
    stage_id: Mapped[str] = mapped_column(
        String, ForeignKey("stages.stage_id"), primary_key=True
    )
    term: Mapped[str] = mapped_column(String, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("stage_id", "display_order", name="uq_concepts_stage_order"),
        Index("ix_concepts_stage_order", "stage_id", "display_order"),
    )


class UserConceptProgressRow(LearningManagementBase):
    __tablename__ = "user_concept_progress"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    concept_id: Mapped[str] = mapped_column(String, primary_key=True)
    stage_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_passed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["concept_id", "stage_id"],
            ["concepts.concept_id", "concepts.stage_id"],
        ),
        CheckConstraint(
            "status IN ('not_started', 'in_progress', 'passed')",
            name="ck_user_concept_progress_status",
        ),
        Index(
            "uq_user_concept_progress_one_in_progress",
            "user_id",
            unique=True,
            sqlite_where=text("status = 'in_progress'"),
            postgresql_where=text("status = 'in_progress'"),
        ),
        Index("ix_user_concept_progress_user_stage", "user_id", "stage_id"),
    )


class UserStageProgressRow(LearningManagementBase):
    __tablename__ = "user_stage_progress"

    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    stage_id: Mapped[str] = mapped_column(
        String, ForeignKey("stages.stage_id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'completed')",
            name="ck_user_stage_progress_status",
        ),
        Index("ix_user_stage_progress_user", "user_id"),
    )


class LearningEventRow(LearningManagementBase):
    __tablename__ = "learning_events"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('concept_passed', 'stage_completed')",
            name="ck_learning_events_type",
        ),
        Index("ix_learning_events_unprocessed", "processed_at", "occurred_at"),
    )


class QuizResultReceiptRow(LearningManagementBase):
    """학습 관리 내부용. submission_id 멱등 처리 결과를 보존한다."""

    __tablename__ = "quiz_result_receipts"

    submission_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    concept_id: Mapped[str] = mapped_column(String, nullable=False)
    stage_id: Mapped[str] = mapped_column(String, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class QuizRetryRequestRow(LearningManagementBase):
    """학습 관리 내부용. 퀴즈 재요청의 Idempotency-Key 결과를 보존한다."""

    __tablename__ = "quiz_retry_requests"

    request_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    original_session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    retry_session_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    response_payload: Mapped[dict[str, Any]] = mapped_column(_json_type(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_quiz_retry_user_key"
        ),
    )


def create_database_engine(db_url: str) -> Engine:
    connect_args: dict[str, Any] = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(db_url, connect_args=connect_args)


def initialize_learning_management_schema(
    engine: Engine,
    stages_json_path: str | Path,
    *,
    auto_create: bool = True,
) -> None:
    """설정에 따라 스키마·시드를 만들거나 배포 준비 상태만 검증한다."""

    if auto_create:
        LearningManagementBase.metadata.create_all(engine)
        seed_learning_catalog(engine, stages_json_path)
        if engine.dialect.name == "sqlite":
            migrate_legacy_development_status(engine)
        return
    require_database_tables(engine, LEARNING_MANAGEMENT_TABLES, require_catalog_seed=True)


def require_database_tables(
    engine: Engine,
    expected_tables: set[str],
    *,
    require_catalog_seed: bool = False,
) -> None:
    """자동 DDL이 꺼진 환경에서 migration과 카탈로그 시드를 확인한다."""

    actual = set(inspect(engine).get_table_names())
    missing = sorted(expected_tables - actual)
    if missing:
        raise DatabaseSchemaNotReadyError(
            "DB_AUTO_CREATE=false인데 필요한 테이블이 없습니다: "
            f"{', '.join(missing)}. migrations SQL(001 → 002 → 003 → 004)을 먼저 적용하세요."
        )
    if require_catalog_seed:
        with engine.connect() as connection:
            stage_count = int(connection.scalar(text("SELECT count(*) FROM stages")) or 0)
            concept_count = int(connection.scalar(text("SELECT count(*) FROM concepts")) or 0)
        if stage_count == 0 or concept_count == 0:
            raise DatabaseSchemaNotReadyError(
                "DB_AUTO_CREATE=false인데 stages/concepts 시드가 없습니다. "
                "migrations/003_seed_stages_concepts.sql을 먼저 적용하세요."
            )


def seed_learning_catalog(engine: Engine, stages_json_path: str | Path) -> None:
    """stages.json을 멱등하게 stages·concepts 테이블에 반영한다."""

    source = Path(stages_json_path)
    data = json.loads(source.read_text(encoding="utf-8"))
    with Session(engine) as session:
        for fallback_order, item in enumerate(data["stages"], start=1):
            stage_id = str(item["id"])
            stage = session.get(StageRow, stage_id)
            values = {
                "name_ko": str(item["name_ko"]),
                "display_order": int(item.get("order", fallback_order)),
                "is_optional": bool(item.get("is_optional", False)),
            }
            if stage is None:
                stage = StageRow(stage_id=stage_id, **values)
                session.add(stage)
            else:
                for key, value in values.items():
                    setattr(stage, key, value)
            for fallback_concept_order, concept_item in enumerate(
                item["concepts"], start=1
            ):
                key = (str(concept_item["concept_id"]), stage_id)
                concept = session.get(ConceptRow, key)
                concept_values = {
                    "term": str(concept_item["term"]),
                    "display_order": int(
                        concept_item.get("order", fallback_concept_order)
                    ),
                }
                if concept is None:
                    session.add(
                        ConceptRow(
                            concept_id=key[0],
                            stage_id=key[1],
                            **concept_values,
                        )
                    )
                else:
                    for name, value in concept_values.items():
                        setattr(concept, name, value)
        session.commit()


def migrate_legacy_development_status(engine: Engine) -> None:
    """dev_concept_status 데이터를 실제 진행 테이블로 옮긴 뒤 이전 테이블을 제거한다."""

    table_names = set(inspect(engine).get_table_names())
    if "dev_concept_status" not in table_names:
        _drop_legacy_stage_override(engine, table_names)
        return
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("dev_concept_status")
    }
    id_column = "concept_id" if "concept_id" in columns else "doc_id"
    if id_column not in columns or "stage_id" not in columns:
        raise RuntimeError("dev_concept_status 데이터 구조를 이전할 수 없습니다.")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT user_id, "
                f"{id_column} AS concept_id, stage_id, status, updated_at "
                "FROM dev_concept_status"
            )
        ).mappings().all()
    with Session(engine) as session:
        for item in rows:
            key = (str(item["user_id"]), str(item["concept_id"]), str(item["stage_id"]))
            if session.get(ConceptRow, (key[1], key[2])) is None:
                continue
            status = _normalize_legacy_status(str(item["status"]))
            updated_at = _coerce_utc(item["updated_at"])
            target = session.get(UserConceptProgressRow, key)
            if target is None:
                session.add(
                    UserConceptProgressRow(
                        user_id=key[0],
                        concept_id=key[1],
                        stage_id=key[2],
                        status=status,
                        started_at=(
                            updated_at if status in {"in_progress", "passed"} else None
                        ),
                        first_passed_at=updated_at if status == "passed" else None,
                        updated_at=updated_at,
                    )
                )
            elif target.updated_at <= updated_at:
                target.status = status
                target.started_at = target.started_at or (
                    updated_at if status in {"in_progress", "passed"} else None
                )
                if status == "passed" and target.first_passed_at is None:
                    target.first_passed_at = updated_at
                target.updated_at = updated_at
        session.commit()
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE dev_concept_status")
    _drop_legacy_stage_override(engine, set(inspect(engine).get_table_names()))


def _drop_legacy_stage_override(engine: Engine, table_names: set[str]) -> None:
    if "dev_user_stage" in table_names:
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE dev_user_stage")


def _normalize_legacy_status(value: str) -> str:
    aliases = {
        "\ubbf8\ud559\uc2b5": "not_started",
        "\ubbf8\ud1b5\uacfc": "in_progress",
        "failed": "in_progress",
        "\ud1b5\uacfc": "passed",
    }
    normalized = aliases.get(value, value)
    if normalized not in CONCEPT_STATUSES:
        raise RuntimeError(f"알 수 없는 이전 개념 상태입니다: {value}")
    return normalized


def _coerce_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def list_seeded_stage_ids(engine: Engine) -> list[str]:
    """시드 스크립트와 테스트에서 사용할 간단한 확인 함수."""

    with Session(engine) as session:
        return list(
            session.scalars(select(StageRow.stage_id).order_by(StageRow.display_order))
        )
