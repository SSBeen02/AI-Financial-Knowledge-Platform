from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from chatbot.integrations import (
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_UNLEARNED,
    ConceptStatusError,
    ConceptStatusService,
    DevConceptStatusService,
    DevUserStageRow,
    FailedConcept,
    get_current_user_id,
)
from tests.conftest import make_settings

STAGE1 = "stage1"
DIVISION = "sisa_1281"
WORKING_POOR = "sisa_1963"
STAGE5_ONLY = "sisa_1552"
USER = "user-1"


def test_new_user_starts_on_stage1_all_unlearned(dev_status: DevConceptStatusService) -> None:
    assert dev_status.get_current_stage(USER) == STAGE1
    statuses = dev_status.get_statuses(USER, STAGE1)
    assert len(statuses) == 30
    assert set(statuses.values()) == {STATUS_UNLEARNED}
    assert statuses[DIVISION] == STATUS_UNLEARNED
    assert dev_status.get_failed_concept(USER) is None


def test_dev_tables_are_not_created_when_local_status_is_disabled(tmp_path: Path) -> None:
    db_path = tmp_path / "disabled.db"
    settings = make_settings(db_path, simulate_quiz_status=False).model_copy(
        update={"dev_use_local_status": False}
    )

    with pytest.raises(ConceptStatusError, match="DEV_USE_LOCAL_STATUS=true"):
        DevConceptStatusService(settings)

    assert not db_path.exists()


def test_current_stage_is_read_from_sqlite(dev_status: DevConceptStatusService) -> None:
    with Session(dev_status._engine) as session:
        session.add(DevUserStageRow(user_id=USER, stage_id="stage3"))
        session.commit()
    assert dev_status.get_current_stage(USER) == "stage3"


def test_mark_failed_only_from_unlearned(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_failed(USER, DIVISION)
    dev_status.mark_failed(USER, DIVISION)
    failed = dev_status.get_failed_concept(USER)
    assert failed == FailedConcept(
        doc_id=DIVISION,
        term="분업/특화",
        term_full="분업/특화",
        stage=STAGE1,
        status=STATUS_FAILED,
    )
    assert dev_status.get_statuses(USER, STAGE1)[DIVISION] == STATUS_FAILED


def test_second_failed_concept_is_rejected(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_failed(USER, DIVISION)
    with pytest.raises(ConceptStatusError):
        dev_status.mark_failed(USER, WORKING_POOR)
    assert dev_status.get_statuses(USER, STAGE1)[WORKING_POOR] == STATUS_UNLEARNED


def test_unknown_or_other_stage_concept_is_rejected(dev_status: DevConceptStatusService) -> None:
    with pytest.raises(ConceptStatusError):
        dev_status.mark_failed(USER, "sisa_missing")
    with pytest.raises(ConceptStatusError):
        dev_status.mark_failed(USER, STAGE5_ONLY)
    assert dev_status.get_failed_concept(USER) is None


def test_explicit_stage5_concept_can_be_marked_failed(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_failed(USER, STAGE5_ONLY, stage="stage5")
    failed = dev_status.get_failed_concept(USER)
    assert failed is not None
    assert failed.doc_id == STAGE5_ONLY
    assert failed.stage == "stage5"
    assert dev_status.get_current_stage(USER) == STAGE1
    assert dev_status.get_statuses(USER, "stage5")[STAGE5_ONLY] == STATUS_FAILED


def test_users_are_isolated(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_failed(USER, DIVISION)
    assert dev_status.get_failed_concept("user-2") is None
    assert dev_status.get_statuses("user-2", STAGE1)[DIVISION] == STATUS_UNLEARNED


def test_status_survives_reopen(status_db: Path) -> None:
    first = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=False))
    first.mark_failed(USER, DIVISION)
    first.close()

    second = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=False))
    try:
        failed = second.get_failed_concept(USER)
        assert failed is not None
        assert failed.doc_id == DIVISION
        assert second.get_statuses(USER, STAGE1)[DIVISION] == STATUS_FAILED
    finally:
        second.close()


def test_dev_quiz_pass_marks_concept_passed_and_leaves_others_unlearned(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.mark_failed(USER, DIVISION)
        service.note_quiz_result(USER, DIVISION, passed=True)
        statuses = service.get_statuses(USER, STAGE1)
        assert statuses[DIVISION] == STATUS_PASSED
        unlearned = [doc_id for doc_id, status in statuses.items() if status == STATUS_UNLEARNED]
        assert DIVISION not in unlearned
        assert len(unlearned) == 29
        assert service.get_failed_concept(USER) is None
    finally:
        service.close()


def test_quiz_pass_hook_off_keeps_failed_status(dev_status: DevConceptStatusService) -> None:
    dev_status.mark_failed(USER, DIVISION)
    dev_status.note_quiz_result(USER, DIVISION, passed=True)
    assert dev_status.get_statuses(USER, STAGE1)[DIVISION] == STATUS_FAILED
    failed = dev_status.get_failed_concept(USER)
    assert failed is not None
    assert failed.doc_id == DIVISION


def test_failed_quiz_report_does_not_change_status(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.mark_failed(USER, DIVISION)
        service.note_quiz_result(USER, DIVISION, passed=False)
        assert service.get_statuses(USER, STAGE1)[DIVISION] == STATUS_FAILED
    finally:
        service.close()


def test_pass_hook_ignores_unlearned_concept(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.note_quiz_result(USER, DIVISION, passed=True)
        assert service.get_statuses(USER, STAGE1)[DIVISION] == STATUS_UNLEARNED
    finally:
        service.close()


def test_passed_concept_cannot_be_marked_failed(status_db: Path) -> None:
    service = DevConceptStatusService(make_settings(status_db, simulate_quiz_status=True))
    try:
        service.mark_failed(USER, DIVISION)
        service.note_quiz_result(USER, DIVISION, passed=True)
        with pytest.raises(ConceptStatusError):
            service.mark_failed(USER, DIVISION)
        assert service.get_statuses(USER, STAGE1)[DIVISION] == STATUS_PASSED
    finally:
        service.close()


class DictStatusService(ConceptStatusService):
    """인터페이스 기본 훅이 상태를 쓰지 않는지 확인하는 테스트 구현."""

    def __init__(self) -> None:
        self.statuses: dict[str, str] = {}

    def get_current_stage(self, user_id: str) -> str:
        return STAGE1

    def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
        return dict(self.statuses)

    def get_failed_concept(self, user_id: str) -> FailedConcept | None:
        for doc_id, status in self.statuses.items():
            if status == STATUS_FAILED:
                return FailedConcept(doc_id, doc_id, doc_id, STAGE1, status)
        return None

    def mark_failed(self, user_id: str, doc_id: str, stage: str | None = None) -> None:
        self.statuses[doc_id] = STATUS_FAILED


def test_interface_hook_does_not_change_concept_status() -> None:
    service = DictStatusService()
    service.mark_failed(USER, DIVISION)
    service.note_quiz_result(USER, DIVISION, passed=True)
    assert service.statuses[DIVISION] == STATUS_FAILED


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
