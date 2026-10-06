from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbot.integrations import SqlConceptStatusService
from chatbot.learning_management import (
    ConceptRow,
    UserConceptProgressRow,
    UserStageProgressRow,
)
from chatbot.store import SqlChatStore
from tests.conftest import make_settings

USER = "learning-user"
CONCEPT = "sisa_1281"
STAGE = "stage1"


def _completed_attempt(
    service: SqlConceptStatusService,
    store: SqlChatStore,
) -> str:
    service.mark_in_progress(USER, CONCEPT, STAGE)
    learning_session = store.create_session(
        user_id=USER,
        stage=STAGE,
        concept_id=CONCEPT,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    store.complete_session_with_context(
        user_id=USER,
        session_id=learning_session.session_id,
        concept_id=CONCEPT,
        idempotency_key=f"complete-{learning_session.session_id}",
        payload={"session_id": learning_session.session_id},
        completed_at=datetime.now(timezone.utc),
    )
    return learning_session.session_id


def test_first_learning_start_opens_stage1(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "stage.db", simulate_quiz_status=False)
    store = SqlChatStore(settings)
    service = SqlConceptStatusService(settings)
    try:
        with Session(service._engine) as db:
            assert db.get(UserStageProgressRow, (USER, STAGE)) is None
        service.mark_in_progress(USER, CONCEPT, STAGE)
        with Session(service._engine) as db:
            row = db.get(UserStageProgressRow, (USER, STAGE))
            assert row is not None
            assert row.status == "in_progress"
    finally:
        service.close()
        store.close()


def test_failed_result_is_idempotent_and_keeps_in_progress(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "failed.db", simulate_quiz_status=False)
    store = SqlChatStore(settings)
    service = SqlConceptStatusService(settings)
    try:
        session_id = _completed_attempt(service, store)
        args = dict(
            user_id=USER,
            submission_id="submission-failed",
            session_id=session_id,
            concept_id=CONCEPT,
            stage_id=STAGE,
            correct_count=1,
            passed=False,
        )
        first = service.apply_quiz_result(**args)
        second = service.apply_quiz_result(**args)
        assert first == second
        assert first["concept_status"] == "in_progress"
        assert first["quiz_status"] == "failed"
        assert service.get_concept_status(USER, CONCEPT, STAGE) == "in_progress"
        assert service.get_unprocessed_events() == []
    finally:
        service.close()
        store.close()


def test_pass_records_one_event_and_preserves_first_passed_at(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "passed.db", simulate_quiz_status=False)
    store = SqlChatStore(settings)
    service = SqlConceptStatusService(settings)
    try:
        session_id = _completed_attempt(service, store)
        args = dict(
            user_id=USER,
            submission_id="submission-passed",
            session_id=session_id,
            concept_id=CONCEPT,
            stage_id=STAGE,
            correct_count=2,
            passed=True,
        )
        first = service.apply_quiz_result(**args)
        second = service.apply_quiz_result(**args)
        assert first == second
        assert service.get_concept_status(USER, CONCEPT, STAGE) == "passed"
        events = service.get_unprocessed_events()
        assert len(events) == 1
        assert events[0].event_type == "concept_passed"
        assert events[0].payload["concept_id"] == CONCEPT
        processed = service.mark_event_processed(events[0].event_id)
        assert processed.processed_at is not None
        assert service.get_unprocessed_events() == []
        with Session(service._engine) as db:
            progress = db.get(UserConceptProgressRow, (USER, CONCEPT, STAGE))
            assert progress is not None and progress.first_passed_at is not None
    finally:
        service.close()
        store.close()


def test_last_concept_pass_completes_stage_and_opens_next(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "last.db", simulate_quiz_status=False)
    store = SqlChatStore(settings)
    service = SqlConceptStatusService(settings)
    try:
        session_id = _completed_attempt(service, store)
        now = datetime.now(timezone.utc)
        with Session(service._engine) as db:
            concepts = list(
                db.scalars(
                    select(ConceptRow).where(
                        ConceptRow.stage_id == STAGE,
                        ConceptRow.concept_id != CONCEPT,
                    )
                )
            )
            db.add_all(
                [
                    UserConceptProgressRow(
                        user_id=USER,
                        concept_id=item.concept_id,
                        stage_id=STAGE,
                        status="passed",
                        started_at=now,
                        first_passed_at=now,
                        updated_at=now,
                    )
                    for item in concepts
                ]
            )
            db.commit()
        result = service.apply_quiz_result(
            user_id=USER,
            submission_id="submission-last",
            session_id=session_id,
            concept_id=CONCEPT,
            stage_id=STAGE,
            correct_count=3,
            passed=True,
        )
        assert result["stage_completed"] is True
        assert result["next_stage_id"] == "stage2"
        assert service.get_current_stage(USER) == "stage2"
        assert [event.event_type for event in service.get_unprocessed_events()] == [
            "concept_passed",
            "stage_completed",
        ]
        with Session(service._engine) as db:
            assert db.get(UserStageProgressRow, (USER, STAGE)).status == "completed"
            assert db.get(UserStageProgressRow, (USER, "stage2")).status == "in_progress"
    finally:
        service.close()
        store.close()
