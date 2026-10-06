from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatbot.learning_management import (
    ConceptRow,
    DatabaseSchemaNotReadyError,
    LearningManagementBase,
    StageRow,
    UserConceptProgressRow,
    create_database_engine,
    initialize_learning_management_schema,
    seed_learning_catalog,
)
from tests.conftest import STAGES_PATH


EXPECTED_TABLES = {
    "stages",
    "concepts",
    "user_concept_progress",
    "user_stage_progress",
    "learning_events",
    "quiz_result_receipts",
    "quiz_retry_requests",
}


def _engine(path: Path):
    return create_database_engine(f"sqlite:///{path.as_posix()}")


def test_schema_and_catalog_seed_are_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "learning.db")
    try:
        initialize_learning_management_schema(engine, STAGES_PATH)
        seed_learning_catalog(engine, STAGES_PATH)

        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
        with Session(engine) as session:
            stages = session.scalars(
                select(StageRow).order_by(StageRow.display_order)
            ).all()
            concepts = session.scalars(select(ConceptRow)).all()
            stage5_count = len(
                session.scalars(
                    select(ConceptRow).where(ConceptRow.stage_id == "stage5")
                ).all()
            )
        assert [stage.stage_id for stage in stages] == [
            "stage1",
            "stage2",
            "stage3",
            "stage4",
            "stage5",
        ]
        assert len(concepts) == 250
        assert stage5_count == 70
    finally:
        engine.dispose()


def test_legacy_development_status_is_preserved_and_table_removed(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "legacy.db")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE dev_concept_status ("
                "user_id VARCHAR NOT NULL, concept_id VARCHAR NOT NULL, "
                "stage_id VARCHAR NOT NULL, status VARCHAR NOT NULL, "
                "updated_at DATETIME NOT NULL, "
                "PRIMARY KEY (user_id, concept_id, stage_id))"
            )
            connection.exec_driver_sql(
                "INSERT INTO dev_concept_status VALUES "
                "('legacy-user', 'sisa_1281', 'stage1', 'in_progress', "
                "'2026-10-04T00:00:00+00:00')"
            )

        initialize_learning_management_schema(engine, STAGES_PATH)

        with Session(engine) as session:
            row = session.get(
                UserConceptProgressRow,
                ("legacy-user", "sisa_1281", "stage1"),
            )
            assert row is not None
            assert row.status == "in_progress"
            assert row.started_at is not None
        assert "dev_concept_status" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_database_allows_only_one_in_progress_concept_per_user(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path / "constraint.db")
    initialize_learning_management_schema(engine, STAGES_PATH)
    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as session:
            session.add_all(
                [
                    UserConceptProgressRow(
                        user_id="user-1",
                        concept_id="sisa_1281",
                        stage_id="stage1",
                        status="in_progress",
                        started_at=now,
                        first_passed_at=None,
                        updated_at=now,
                    ),
                    UserConceptProgressRow(
                        user_id="user-1",
                        concept_id="sisa_745",
                        stage_id="stage3",
                        status="in_progress",
                        started_at=now,
                        first_passed_at=None,
                        updated_at=now,
                    ),
                ]
            )
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()


def test_postgresql_migration_keeps_internal_idempotency_tables() -> None:
    sql = (Path(__file__).parents[1] / "migrations" / "001_learning_management.sql").read_text(
        encoding="utf-8"
    )
    for table in EXPECTED_TABLES:
        assert f"create table if not exists {table}" in sql.lower()
    assert "where status = 'in_progress'" in sql


def test_disabled_auto_create_requires_migrations_and_seed(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "empty.db")
    try:
        with pytest.raises(DatabaseSchemaNotReadyError, match="001 → 002 → 003"):
            initialize_learning_management_schema(
                engine,
                STAGES_PATH,
                auto_create=False,
            )
    finally:
        engine.dispose()


def test_rls_migration_covers_all_module_tables_without_policies() -> None:
    sql = (Path(__file__).parents[1] / "migrations" / "002_enable_rls.sql").read_text(
        encoding="utf-8"
    ).lower()
    expected = EXPECTED_TABLES | {
        "learning_sessions",
        "learning_messages",
        "learning_contexts",
        "learning_completion_requests",
    }
    for table in expected:
        assert f"alter table public.{table} enable row level security" in sql
    assert "create policy" not in sql


def test_generated_supabase_seed_contains_all_catalog_rows() -> None:
    sql = (
        Path(__file__).parents[1] / "migrations" / "003_seed_stages_concepts.sql"
    ).read_text(encoding="utf-8")
    assert sql.count("insert into public.stages") == 5
    assert sql.count("insert into public.concepts") == 250
    assert "on conflict (concept_id, stage_id) do update" in sql


def test_fourth_migration_renames_learning_session_stage_column() -> None:
    sql = (
        Path(__file__).parents[1]
        / "migrations"
        / "004_rename_learning_sessions_stage.sql"
    ).read_text(encoding="utf-8").lower()
    assert "alter table public.learning_sessions rename column stage to stage_id" in sql
