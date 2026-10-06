from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatbot.concepts import load_stage_catalog
from chatbot.deps import get_chat_store, get_concept_status_service, get_stage_catalog
from chatbot.integrations import (
    STATUS_IN_PROGRESS,
    SqlConceptStatusService,
    InProgressConcept,
)
from chatbot.learning_management import UserConceptProgressRow
from chatbot.router import router
from chatbot.store import SqlChatStore
from tests.conftest import STAGES_PATH, force_concept_status, make_client, make_settings

STAGE1 = "stage1"
DIVISION = "sisa_1281"
OPPORTUNITY_COST = "sisa_745"
USER = "user-1"
HEADERS = {"X-User-Id": USER}

FIRST_FIVE = [
    {
        "concept_id": "sisa_1281",
        "term": "분업/특화",
        "term_full": "분업/특화",
        "subcategory": "경제 기본",
        "order": 1,
    },
    {
        "concept_id": "sisa_1963",
        "term": "워킹푸어",
        "term_full": "워킹푸어(Working Poor)",
        "subcategory": "청년·일자리",
        "order": 2,
    },
    {
        "concept_id": "sisa_980",
        "term": "렌트 푸어",
        "term_full": "렌트 푸어(Rent-Poor)",
        "subcategory": "청년·일자리",
        "order": 3,
    },
    {
        "concept_id": "sisa_1123",
        "term": "민달팽이세대",
        "term_full": "민달팽이세대",
        "subcategory": "청년·일자리",
        "order": 4,
    },
    {
        "concept_id": "sisa_15",
        "term": "88만원세대",
        "term_full": "88만원세대",
        "subcategory": "청년·일자리",
        "order": 5,
    },
]


def test_stage1_first_page_is_unlearned_in_order(client: TestClient) -> None:
    response = client.get("/learning/concepts", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {
        "mode": "normal",
        "stage_id": "stage1",
        "stage_name_ko": "사회경제현상과 소비생활",
        "concepts": FIRST_FIVE,
        "next_offset": 5,
        "has_more": True,
        "locked_concept": None,
        "notice": None,
        "suggested_message": None,
    }


def test_second_page_continues_in_order(client: TestClient) -> None:
    response = client.get("/learning/concepts", params={"offset": 5, "limit": 5}, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert [item["concept_id"] for item in body["concepts"]] == [
        "sisa_842",
        "sisa_2375",
        "sisa_2011",
        "sisa_1704",
        "sisa_419",
    ]
    assert [item["order"] for item in body["concepts"]] == [6, 7, 8, 9, 10]
    assert body["next_offset"] == 10
    assert body["has_more"] is True


def test_last_page_has_no_next_offset(client: TestClient) -> None:
    response = client.get("/learning/concepts", params={"offset": 25}, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert len(body["concepts"]) == 5
    assert body["concepts"][0]["order"] == 26
    assert body["concepts"][-1]["order"] == 30
    assert body["has_more"] is False
    assert body["next_offset"] is None


def test_offset_past_the_end_is_empty(client: TestClient) -> None:
    response = client.get("/learning/concepts", params={"offset": 30}, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["concepts"] == []
    assert body["has_more"] is False
    assert body["next_offset"] is None


def test_passed_concept_is_left_out(status_db) -> None:
    settings = make_settings(status_db, simulate_quiz_status=True)
    service = SqlConceptStatusService(settings)
    store = SqlChatStore(settings)
    try:
        service.mark_in_progress(USER, DIVISION, STAGE1)
        force_concept_status(service, USER, DIVISION, STAGE1, "passed")
        body = make_client(service, store).get("/learning/concepts", params={"limit": 30}, headers=HEADERS).json()
    finally:
        service.close()
        store.close()

    concept_ids = [item["concept_id"] for item in body["concepts"]]
    assert body["mode"] == "normal"
    assert body["locked_concept"] is None
    assert DIVISION not in concept_ids
    assert concept_ids[0] == "sisa_1963"
    assert len(concept_ids) == 29
    assert body["has_more"] is False


def _record_quiz(store: SqlChatStore, quiz_status: str) -> None:
    record = store.create_session(
        user_id=USER,
        stage=STAGE1,
        concept_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
        status="completed",
    )
    store.save_learning_context(
        session_id=record.session_id,
        user_id=USER,
        concept_id=DIVISION,
        payload={},
        quiz_status=quiz_status,  # type: ignore[arg-type]
    )


def test_relearn_mode_locks_in_progress_concept_after_failed_quiz(
    client: TestClient, dev_status: SqlConceptStatusService, chat_store: SqlChatStore
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    _record_quiz(chat_store, "failed")
    response = client.get("/learning/concepts", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "relearn"
    assert body["locked_concept"] == FIRST_FIVE[0]
    assert body["notice"] == (
        "지금 분업/특화 개념을 학습 중이오. 이 개념을 통과해야 다음 개념으로 넘어갈 수 있소."
    )
    assert body["suggested_message"] == "분업/특화에 대해 다시 알려줘"
    assert [item["concept_id"] for item in body["concepts"]] == [
        "sisa_1963",
        "sisa_980",
        "sisa_1123",
        "sisa_15",
        "sisa_842",
    ]
    assert body["has_more"] is True
    assert body["next_offset"] == 5


def test_passed_quiz_before_status_update_is_quiz_pending(
    client: TestClient, dev_status: SqlConceptStatusService, chat_store: SqlChatStore
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    _record_quiz(chat_store, "passed")
    body = client.get("/learning/concepts", headers=HEADERS).json()
    assert dev_status.get_statuses(USER, STAGE1)[DIVISION] == STATUS_IN_PROGRESS
    assert body["mode"] == "quiz_pending"
    assert body["locked_concept"]["concept_id"] == DIVISION
    assert body["notice"] == "현재 분업/특화 개념의 퀴즈 결과를 기다리는 중이오."
    assert body["suggested_message"] is None


def test_concepts_always_use_current_stage(
    client: TestClient, dev_status: SqlConceptStatusService
) -> None:
    dev_status.set_current_stage(USER, "stage5")
    body = client.get("/learning/concepts", headers=HEADERS).json()
    assert body["mode"] == "normal"
    assert body["stage_id"] == "stage5"
    assert body["stage_name_ko"] == "TESAT·매경TEST 빈출 핵심 용어"
    assert body["concepts"][0] == {
        "concept_id": "sisa_1552",
        "term": "수요의 법칙",
        "term_full": "수요의 법칙(Law of Demand)",
        "subcategory": "미시경제",
        "order": 1,
    }

    ignored = client.get("/learning/concepts", params={"stage": "stage1"}, headers=HEADERS)
    assert ignored.status_code == 200
    assert ignored.json()["stage_id"] == "stage5"


def test_stage1_all_passed_advances_concepts_to_stage2(
    client: TestClient, dev_status: SqlConceptStatusService
) -> None:
    dev_status.pass_stage(USER, "stage1")
    body = client.get("/learning/concepts", headers=HEADERS).json()
    assert body["stage_id"] == "stage2"


def test_stage4_all_passed_advances_concepts_to_stage5(
    client: TestClient, dev_status: SqlConceptStatusService
) -> None:
    dev_status.set_current_stage(USER, "stage4")
    dev_status.pass_stage(USER, "stage4")
    body = client.get("/learning/concepts", headers=HEADERS).json()
    assert body["stage_id"] == "stage5"


def test_stage1_stays_current_while_one_in_progress_concept_remains(
    client: TestClient, dev_status: SqlConceptStatusService
) -> None:
    dev_status.pass_stage(USER, "stage1")
    with Session(dev_status._engine) as session:
        row = session.get(UserConceptProgressRow, (USER, DIVISION, "stage1"))
        assert row is not None
        row.status = STATUS_IN_PROGRESS
        session.commit()
    body = client.get("/learning/concepts", headers=HEADERS).json()
    assert body["stage_id"] == "stage1"


def test_stage5_recommends_doc_passed_in_stage3(
    client: TestClient, dev_status: SqlConceptStatusService, chat_store: SqlChatStore
) -> None:
    dev_status.set_current_stage(USER, "stage3")
    dev_status.mark_in_progress(USER, OPPORTUNITY_COST, "stage3")
    force_concept_status(dev_status, USER, OPPORTUNITY_COST, "stage3", "passed")
    dev_status.set_current_stage(USER, "stage5")
    body = client.get("/learning/concepts", params={"limit": 70}, headers=HEADERS).json()
    assert body["stage_id"] == "stage5"
    assert OPPORTUNITY_COST in [item["concept_id"] for item in body["concepts"]]


def test_users_are_isolated(client: TestClient, dev_status: SqlConceptStatusService) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    body = client.get("/learning/concepts", headers={"X-User-Id": "user-2"}).json()
    assert body["mode"] == "normal"
    assert body["concepts"][0]["concept_id"] == DIVISION
    assert body["locked_concept"] is None


def test_query_user_id_is_ignored(
    client: TestClient, dev_status: SqlConceptStatusService, chat_store: SqlChatStore
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    _record_quiz(chat_store, "failed")
    body = client.get("/learning/concepts", params={"user_id": "user-2"}, headers=HEADERS).json()
    assert body["mode"] == "relearn"
    assert body["locked_concept"]["concept_id"] == DIVISION


def test_missing_user_header_is_unauthorized(client: TestClient) -> None:
    assert client.get("/learning/concepts").status_code == 401
    assert client.get("/learning/concepts", headers={"X-User-Id": "  "}).status_code == 401


def test_invalid_paging_is_rejected(client: TestClient) -> None:
    assert client.get("/learning/concepts", params={"offset": -1}, headers=HEADERS).status_code == 422
    assert client.get("/learning/concepts", params={"limit": 0}, headers=HEADERS).status_code == 422


def test_database_rejects_multiple_in_progress_concepts(
    dev_status: SqlConceptStatusService,
) -> None:
    now = datetime.now(timezone.utc)
    with Session(dev_status._engine) as session:
        session.add_all(
            [
                UserConceptProgressRow(
                    user_id=USER,
                    concept_id=DIVISION,
                    stage_id=STAGE1,
                    status=STATUS_IN_PROGRESS,
                    updated_at=now,
                ),
                UserConceptProgressRow(
                    user_id=USER,
                    concept_id="sisa_1963",
                    stage_id=STAGE1,
                    status=STATUS_IN_PROGRESS,
                    updated_at=now,
                ),
            ]
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_missing_locked_concept_is_server_error() -> None:
    class BrokenStatus:
        def get_current_stage(self, user_id: str) -> str:
            return STAGE1

        def get_statuses(self, user_id: str, stage: str) -> dict[str, str]:
            return {}

        def get_in_progress_concept(self, user_id: str, stage: str) -> InProgressConcept:
            return InProgressConcept("sisa_missing", "없는개념", "없는개념", STAGE1, STATUS_IN_PROGRESS)

    class EmptyStore:
        def get_latest_quiz(self, user_id: str, concept_id: str, stage: str) -> object:
            return type("Latest", (), {"quiz_status": "failed"})()

        def get_active_session(self, user_id: str) -> None:
            return None

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_concept_status_service] = lambda: BrokenStatus()
    app.dependency_overrides[get_stage_catalog] = lambda: load_stage_catalog(STAGES_PATH)
    app.dependency_overrides[get_chat_store] = lambda: EmptyStore()
    response = TestClient(app, raise_server_exceptions=False).get("/learning/concepts", headers=HEADERS)
    assert response.status_code == 500
