from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from chatbot.integrations import (
    STATUS_IN_PROGRESS,
    STATUS_PASSED,
    STATUS_NOT_STARTED,
    ConceptStatusError,
    ConceptStatusService,
    DevConceptStatusService,
    InProgressConcept,
    get_current_user_id,
)
from tests.conftest import make_settings

STAGE1 = "stage1"
STAGE3 = "stage3"
DIVISION = "sisa_1281"
WORKING_POOR = "sisa_1963"
STAGE5_ONLY = "sisa_1552"
OPPORTUNITY_COST = "sisa_745"
USER = "user-1"


def test_new_user_starts_on_stage1_all_unlearned(dev_status: DevConceptStatusService) -> None:
    assert dev_status.get_current_stage(USER) == STAGE1
    statuses = dev_status.get_statuses(USER, STAGE1)
    assert len(statuses) == 30
    assert set(statuses.values()) == {STATUS_NOT_STARTED}
    assert statuses[DIVISION] == STATUS_NOT_STARTED
    assert dev_status.get_in_progress_concept(USER, STAGE1) is None


def test_dev_tables_are_not_created_when_local_status_is_disabled(tmp_path: Path) -> None:
    db_path = tmp_path / "disabled.db"
    settings = make_settings(db_path, simulate_quiz_status=False).model_copy(
        update={"dev_use_local_status": False}
    )

    with pytest.raises(ConceptStatusError, match="DEV_USE_LOCAL_STATUS=true"):
        DevConceptStatusService(settings)

    assert not db_path.exists()


def test_current_stage_is_computed_from_lowest_incomplete_stage(
    dev_status: DevConceptStatusService,
) -> None:
    dev_status.pass_stage(USER, STAGE1)
    assert dev_status.get_current_stage(USER) == "stage2"
    dev_status.set_current_stage(USER, "stage4")
    assert dev_status.get_current_stage(USER) == "stage4"


def test_legacy_user_stage_table_is_removed(status_db: Path) -> None:
    settings = make_settings(status_db, simulate_quiz_status=False)
    engine = create_engine(settings.chat_db_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE dev_user_stage (user_id VARCHAR PRIMARY KEY, stage_id VARCHAR NOT NULL)"
        )
        connection.exec_driver_sql("INSERT INTO dev_user_stage VALUES ('user-1', 'stage5')")
    engine.dispose()

    service = DevConceptStatusService(settings)
    try:
        assert "dev_user_stage" not in inspect(service._engine).get_table_names()
        assert service.get_current_stage(USER) == STAGE1
    finally:
        service.close()


def test_mark_in_progress_only_from_unlearned(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    in_progress = dev_status.get_in_progress_concept(USER, STAGE1)
    assert in_progress == InProgressConcept(
        concept_id=DIVISION,
        term="분업/특화",
        term_full="분업/특화",
        stage=STAGE1,
        status=STATUS_IN_PROGRESS,
    )
    assert dev_status.get_statuses(USER, STAGE1)[DIVISION] == STATUS_IN_PROGRESS


def test_second_in_progress_concept_is_rejected(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    with pytest.raises(ConceptStatusError):
        dev_status.mark_in_progress(USER, WORKING_POOR, STAGE1)
    assert dev_status.get_statuses(USER, STAGE1)[WORKING_POOR] == STATUS_NOT_STARTED


def test_unknown_or_other_stage_concept_is_rejected(dev_status: DevConceptStatusService) -> None:
    with pytest.raises(ConceptStatusError):
        dev_status.mark_in_progress(USER, "sisa_missing", STAGE1)
    with pytest.raises(ConceptStatusError):
        dev_status.mark_in_progress(USER, STAGE5_ONLY, STAGE1)
    assert dev_status.get_in_progress_concept(USER, STAGE1) is None


def test_current_stage5_concept_can_be_marked_in_progress(dev_status: DevConceptStatusService) -> None:
    dev_status.set_current_stage(USER, "stage5")
    dev_status.mark_in_progress(USER, STAGE5_ONLY, "stage5")
    in_progress = dev_status.get_in_progress_concept(USER, "stage5")
    assert in_progress is not None
    assert in_progress.concept_id == STAGE5_ONLY
    assert in_progress.stage == "stage5"
    assert dev_status.get_current_stage(USER) == "stage5"
    assert dev_status.get_statuses(USER, "stage5")[STAGE5_ONLY] == STATUS_IN_PROGRESS


def test_current_stage_stays_stage5_after_every_stage_is_passed(
    dev_status: DevConceptStatusService,
) -> None:
    dev_status.set_current_stage(USER, "stage5")
    dev_status.pass_stage(USER, "stage5")
    assert dev_status.get_current_stage(USER) == "stage5"


def test_users_are_isolated(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    assert dev_status.get_in_progress_concept("user-2", STAGE1) is None
    assert dev_status.get_statuses("user-2", STAGE1)[DIVISION] == STATUS_NOT_STARTED


def test_status_survives_reopen(status_db: Path) -> None:
    first = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=False))
    first.mark_in_progress(USER, DIVISION, STAGE1)
    first.close()

    second = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=False))
    try:
        in_progress = second.get_in_progress_concept(USER, STAGE1)
        assert in_progress is not None
        assert in_progress.concept_id == DIVISION
        assert second.get_statuses(USER, STAGE1)[DIVISION] == STATUS_IN_PROGRESS
    finally:
        second.close()


def test_dev_quiz_pass_marks_concept_passed_and_leaves_others_unlearned(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.mark_in_progress(USER, DIVISION, STAGE1)
        service.note_quiz_result(USER, DIVISION, STAGE1, passed=True)
        statuses = service.get_statuses(USER, STAGE1)
        assert statuses[DIVISION] == STATUS_PASSED
        unlearned = [concept_id for concept_id, status in statuses.items() if status == STATUS_NOT_STARTED]
        assert DIVISION not in unlearned
        assert len(unlearned) == 29
        assert service.get_in_progress_concept(USER, STAGE1) is None
    finally:
        service.close()


def test_quiz_pass_hook_off_keeps_failed_status(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    dev_status.note_quiz_result(USER, DIVISION, STAGE1, passed=True)
    assert dev_status.get_statuses(USER, STAGE1)[DIVISION] == STATUS_IN_PROGRESS
    in_progress = dev_status.get_in_progress_concept(USER, STAGE1)
    assert in_progress is not None
    assert in_progress.concept_id == DIVISION


def test_failed_quiz_report_does_not_change_status(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.mark_in_progress(USER, DIVISION, STAGE1)
        service.note_quiz_result(USER, DIVISION, STAGE1, passed=False)
        assert service.get_statuses(USER, STAGE1)[DIVISION] == STATUS_IN_PROGRESS
    finally:
        service.close()


def test_pass_hook_ignores_unlearned_concept(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.note_quiz_result(USER, DIVISION, STAGE1, passed=True)
        assert service.get_statuses(USER, STAGE1)[DIVISION] == STATUS_NOT_STARTED
    finally:
        service.close()


def test_passed_concept_cannot_be_marked_in_progress(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.mark_in_progress(USER, DIVISION, STAGE1)
        service.note_quiz_result(USER, DIVISION, STAGE1, passed=True)
        with pytest.raises(ConceptStatusError):
            service.mark_in_progress(USER, DIVISION, STAGE1)
        assert service.get_statuses(USER, STAGE1)[DIVISION] == STATUS_PASSED
    finally:
        service.close()


class DictStatusService(ConceptStatusService):
    """인터페이스 기본 훅이 상태를 쓰지 않는지 확인하는 테스트 구현."""

    def __init__(self) -> None:
        self.statuses: dict[str, str] = {}

    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
        return dict(self.statuses)

    def get_in_progress_concept(self, user_id: str, stage: str) -> InProgressConcept | None:
        for concept_id, status in self.statuses.items():
            if status == STATUS_IN_PROGRESS:
                return InProgressConcept(concept_id, concept_id, concept_id, STAGE1, status)
        return None

    def mark_in_progress(self, user_id: str, concept_id: str, stage: str) -> None:
        self.statuses[concept_id] = STATUS_IN_PROGRESS


def test_interface_hook_does_not_change_concept_status() -> None:
    service = DictStatusService()
    service.mark_in_progress(USER, DIVISION, STAGE1)
    service.note_quiz_result(USER, DIVISION, STAGE1, passed=True)
    assert service.statuses[DIVISION] == STATUS_IN_PROGRESS


def test_interface_default_current_stage_uses_statuses() -> None:
    class StageStatuses(ConceptStatusService):
        def __init__(self) -> None:
            self.by_stage = {
                stage: {f"{stage}-concept": STATUS_PASSED}
                for stage in ("stage1", "stage2", "stage3", "stage4", "stage5")
            }

        def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
            return self.by_stage[stage]

        def get_in_progress_concept(self, user_id: str, stage: str) -> InProgressConcept | None:
            return None

        def mark_in_progress(self, user_id: str, concept_id: str, stage: str) -> None:
            return None

    service = StageStatuses()
    assert service.get_current_stage(USER) == "stage5"
    service.by_stage["stage3"]["stage3-concept"] = STATUS_IN_PROGRESS
    assert service.get_current_stage(USER) == "stage3"


def test_same_concept_id_has_independent_stage_status(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.set_current_stage(USER, STAGE3)
        service.mark_in_progress(USER, OPPORTUNITY_COST, STAGE3)
        service.note_quiz_result(USER, OPPORTUNITY_COST, STAGE3, passed=True)
        assert service.get_statuses(USER, STAGE3)[OPPORTUNITY_COST] == STATUS_PASSED

        service.set_current_stage(USER, "stage5")
        assert service.get_statuses(USER, "stage5")[OPPORTUNITY_COST] == STATUS_NOT_STARTED
        service.mark_in_progress(USER, OPPORTUNITY_COST, "stage5")
        assert service.get_statuses(USER, "stage5")[OPPORTUNITY_COST] == STATUS_IN_PROGRESS
        assert service.get_statuses(USER, STAGE3)[OPPORTUNITY_COST] == STATUS_PASSED
    finally:
        service.close()


def test_legacy_dev_status_primary_key_is_migrated(status_db: Path) -> None:
    settings = make_settings(status_db, simulate_quiz_status=False)
    engine = create_engine(settings.chat_db_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE dev_concept_status ("
            "user_id VARCHAR NOT NULL, doc_id VARCHAR NOT NULL, stage_id VARCHAR NOT NULL, "
            "status VARCHAR NOT NULL, updated_at DATETIME NOT NULL, "
            "PRIMARY KEY (user_id, doc_id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO dev_concept_status VALUES "
            "('legacy-user', 'sisa_1281', 'stage1', '미통과', '2026-01-01 00:00:00')"
        )
    engine.dispose()

    service = DevConceptStatusService(settings)
    try:
        assert service.get_statuses("legacy-user", STAGE1)[DIVISION] == STATUS_IN_PROGRESS
        primary_key = set(
            inspect(service._engine)
            .get_pk_constraint("dev_concept_status")["constrained_columns"]
        )
        assert primary_key == {"user_id", "concept_id", "stage_id"}
    finally:
        service.close()


def test_user_id_comes_only_from_header() -> None:
    app = FastAPI()

    @app.get("/me")
    def me(user_id: str = Depends(get_current_user_id)) -> dict[str, str]:
        return {"user_id": user_id}

    client = TestClient(app)
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"X-User-Id": "   "}).status_code == 401
    assert client.get("/me", params={"user_id": USER}).status_code == 401
    response = client.get("/me", headers={"X-User-Id": f"  {USER}  "})
    assert response.status_code == 200
    assert response.json() == {"user_id": USER}
