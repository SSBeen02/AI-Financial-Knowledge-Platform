from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import main_dev
from chatbot.concepts import STATUS_IN_PROGRESS, STATUS_NOT_STARTED, STATUS_PASSED, load_stage_catalog
from chatbot.config import Settings
from chatbot.deps import get_chat_store, get_concept_status_service, get_stage_catalog
from chatbot.dev_tools import router as dev_router
from chatbot.integrations import SqlConceptStatusService
from chatbot.store import SqlChatStore
from tests.conftest import STAGES_PATH, make_settings


def _dev_client(
    service: SqlConceptStatusService,
    store: SqlChatStore,
) -> TestClient:
    app = FastAPI()
    app.include_router(dev_router)
    app.dependency_overrides[get_concept_status_service] = lambda: service
    app.dependency_overrides[get_chat_store] = lambda: store
    app.dependency_overrides[get_stage_catalog] = lambda: load_stage_catalog(STAGES_PATH)
    return TestClient(app)


def _paths(app: FastAPI) -> set[str]:
    return {route.path for route in app.routes if hasattr(route, "path")}


def test_dev_routes_and_page_are_registered_only_for_local_status(status_db) -> None:
    dev_settings = make_settings(status_db, simulate_quiz_status=False)
    prod_settings = Settings(
        _env_file=None,
        llm_model="gpt-test",
        stages_json_path=STAGES_PATH,
        chat_db_url=f"sqlite:///{status_db.as_posix()}",
        dev_enable_tools=False,
    )

    dev_app = main_dev.create_app(dev_settings)
    prod_app = main_dev.create_app(prod_settings)

    assert {"/learning/dev/stage", "/learning/dev/pass-all", "/learning/dev/reset", "/learning/dev/status"} <= set(
        dev_app.openapi()["paths"]
    )
    assert not any(path.startswith("/learning/dev") for path in prod_app.openapi()["paths"])
    assert "/dev/chat" in _paths(dev_app)
    assert "/dev/chat" not in _paths(prod_app)

    response = TestClient(dev_app).get("/dev/chat")
    assert response.status_code == 200
    assert "/learning/messages/stream" in response.text
    assert "display_sources" in response.text
    assert "progressBar" in response.text
    assert "complete_hint" in response.text
    assert "answer-notice" in response.text
    assert "doneMetadata.notice" in response.text
    assert "quick_prompts" in response.text
    assert "learningChip" in response.text
    assert "/quiz-retry" in response.text
    assert "applyLearningBoundary(message)" in response.text
    assert "applyLearningBoundary(doneMetadata, user.item)" in response.text
    assert 'insertBefore(divider, beforeItem)' in response.text
    assert TestClient(prod_app).get("/learning/dev/status?stage=stage1").status_code == 404


def test_dev_stage_and_status_api(dev_status, chat_store) -> None:
    client = _dev_client(dev_status, chat_store)
    headers = {"X-User-Id": "manual-user"}

    changed = client.post("/learning/dev/stage", headers=headers, json={"stage": "stage5"})
    assert changed.status_code == 200
    assert changed.json() == {"stage_id": "stage5"}

    response = client.get("/learning/dev/status?stage=stage5", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["current_stage_id"] == "stage5"
    assert payload["stage_id"] == "stage5"
    assert len(payload["concepts"]) == 70
    assert all(concept["status"] == STATUS_NOT_STARTED for concept in payload["concepts"])
    for stage in ("stage1", "stage2", "stage3", "stage4"):
        statuses = dev_status.get_statuses("manual-user", stage)
        assert all(status == STATUS_PASSED for status in statuses.values())


def test_dev_pass_all_advances_to_next_stage(dev_status, chat_store) -> None:
    client = _dev_client(dev_status, chat_store)
    headers = {"X-User-Id": "manual-user"}

    response = client.post("/learning/dev/pass-all", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"stage_id": "stage2"}
    assert dev_status.get_current_stage("manual-user") == "stage2"
    assert all(
        status == STATUS_PASSED
        for status in dev_status.get_statuses("manual-user", "stage1").values()
    )


def test_dev_reset_clears_only_current_user(dev_status, chat_store) -> None:
    catalog = load_stage_catalog(STAGES_PATH)
    concept_id = catalog.stages["stage1"].concepts[0].concept_id
    for user_id in ("reset-me", "keep-me"):
        dev_status.mark_in_progress(user_id, concept_id, "stage1")
        session = chat_store.create_session(
            user_id=user_id,
            stage="stage1",
            concept_id=concept_id,
            term=catalog.stages["stage1"].concepts[0].term,
            attempt=1,
            start_type="keyword",
        )
        chat_store.save_message_pair(
            user_id=user_id,
            session_id=session.session_id,
            question="질문",
            answer="답변",
            is_related=True,
            band="high",
            top_score=0.9,
            sources=[],
            display_sources=[],
            latency_ms=1,
        )
        chat_store.complete_session(user_id, session.session_id)
        chat_store.save_learning_context(
            session_id=session.session_id,
            user_id=user_id,
            concept_id=concept_id,
            payload={"status": "completed", "concept": {"concept_id": concept_id}},
        )
    dev_status.set_current_stage("reset-me", "stage5")

    client = _dev_client(dev_status, chat_store)
    response = client.post("/learning/dev/reset", headers={"X-User-Id": "reset-me"})

    assert response.status_code == 200
    assert response.json() == {"reset": True, "stage_id": "stage1"}
    assert dev_status.get_current_stage("reset-me") == "stage1"
    assert dev_status.get_statuses("reset-me", "stage1")[concept_id] == STATUS_NOT_STARTED
    assert chat_store.get_recent_messages("reset-me", limit=50) == []
    assert chat_store.list_learning_contexts("reset-me") == []

    assert dev_status.get_statuses("keep-me", "stage1")[concept_id] == STATUS_IN_PROGRESS
    assert len(chat_store.get_recent_messages("keep-me", limit=50)) == 2
    assert len(chat_store.list_learning_contexts("keep-me")) == 1
