from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from chatbot.integrations import DevConceptStatusService
from chatbot.store import ChatSessionRow, LearningContextRow, SqlChatStore
from tests.conftest import make_settings
from tests.test_concepts import DIVISION, HEADERS, USER

STAGE1 = "stage1"
NOTICE = "현재 미통과인 분업/특화 개념 학습중입니다. 통과해야 다음 개념을 넘어갈 수 있습니다."
QUIZ_NOTICE = "현재 분업/특화 개념의 퀴즈 결과를 기다리는 중입니다."


def _modes(client: TestClient, stage: str | None = None) -> tuple[dict, dict]:
    params = {"stage": stage} if stage is not None else None
    state = client.get("/chat/state", headers=HEADERS).json()
    concepts = client.get("/chat/concepts", headers=HEADERS, params=params).json()
    return state, concepts


def _completed(
    store: SqlChatStore,
    *,
    quiz_status: str,
    attempt: int = 1,
    start_type: str = "keyword",
    user_id: str = USER,
) -> str:
    record = store.create_session(
        user_id=user_id,
        stage=STAGE1,
        doc_id=DIVISION,
        term="분업/특화",
        attempt=attempt,
        start_type=start_type,  # type: ignore[arg-type]
        status="completed",
    )
    store.save_learning_context(
        session_id=record.session_id,
        user_id=user_id,
        doc_id=DIVISION,
        payload={"doc_id": DIVISION},
        quiz_status=quiz_status,  # type: ignore[arg-type]
    )
    return record.session_id


def test_mode_priority_is_pending_then_relearn_then_normal(
    client: TestClient,
    dev_status: DevConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "normal"
    assert state == {
        "mode": "normal",
        "active_session": None,
        "locked_concept": None,
        "notice": None,
    }

    dev_status.mark_failed(USER, DIVISION)
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "normal"
    assert state["locked_concept"] is None
    assert state["notice"] is None
    assert concepts["concepts"][0]["doc_id"] == "sisa_1963"

    session_id = _completed(chat_store, quiz_status="failed")
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "relearn"
    assert state["locked_concept"] == concepts["locked_concept"]
    assert state["locked_concept"]["doc_id"] == DIVISION
    assert state["notice"] == concepts["notice"] == NOTICE
    assert concepts["suggested_message"] == "분업/특화에 대해 다시 알려줘"
    assert state["active_session"] is None

    _, stage5 = _modes(client, "stage5")
    assert stage5["mode"] == "relearn"
    assert stage5["stage"]["id"] == "stage5"
    assert stage5["locked_concept"]["doc_id"] == DIVISION
    assert stage5["concepts"][0]["doc_id"] == "sisa_1552"
    assert stage5["notice"] == NOTICE

    chat_store.set_quiz_status(USER, session_id, "pending")
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "quiz_pending"
    assert state["locked_concept"]["doc_id"] == concepts["locked_concept"]["doc_id"] == DIVISION
    assert state["notice"] == concepts["notice"] == QUIZ_NOTICE
    assert concepts["suggested_message"] is None
    assert concepts["concepts"][0]["doc_id"] == "sisa_1963"
    assert state["active_session"] is None
    _, pending_stage5 = _modes(client, "stage5")
    assert pending_stage5["mode"] == "quiz_pending"
    assert pending_stage5["stage"]["id"] == "stage5"
    assert pending_stage5["locked_concept"]["doc_id"] == DIVISION
    assert pending_stage5["notice"] == QUIZ_NOTICE

    chat_store.set_quiz_status(USER, session_id, "passed")
    dev_status.note_quiz_result(USER, DIVISION, passed=True)
    state, concepts = _modes(client)
    assert dev_status.get_failed_concept(USER) is not None
    assert state["mode"] == concepts["mode"] == "quiz_pending"
    assert state["notice"] == QUIZ_NOTICE
    assert concepts["suggested_message"] is None

    chat_store.set_quiz_status(USER, session_id, "failed")
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "relearn"
    assert state["notice"] == NOTICE
    _, failed_stage5 = _modes(client, "stage5")
    assert failed_stage5["mode"] == "relearn"
    assert failed_stage5["locked_concept"]["doc_id"] == DIVISION


def test_state_includes_the_active_relearn_session(
    client: TestClient,
    dev_status: DevConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_failed(USER, DIVISION)
    _completed(chat_store, quiz_status="failed")
    record = chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        doc_id=DIVISION,
        term="분업/특화",
        attempt=2,
        start_type="relearn",
    )
    body = client.get("/chat/state", headers=HEADERS).json()
    assert body["mode"] == "relearn"
    assert body["active_session"]["session_id"] == record.session_id
    assert body["active_session"]["attempt"] == 2
    assert body["active_session"]["start_type"] == "relearn"
    assert body["active_session"]["status"] == "active"
    assert body["active_session"]["completed_at"] is None
    assert "user_id" not in body["active_session"]


def test_learning_without_quiz_record_stays_normal(
    client: TestClient,
    dev_status: DevConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_failed(USER, DIVISION)
    record = chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        doc_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "normal"
    assert state["active_session"]["session_id"] == record.session_id
    assert state["locked_concept"] is None
    assert state["notice"] is None


@pytest.mark.parametrize("quiz_status", ["pending", "passed"])
def test_quiz_pending_cannot_have_active_session(
    client: TestClient,
    dev_status: DevConceptStatusService,
    chat_store: SqlChatStore,
    quiz_status: str,
) -> None:
    dev_status.mark_failed(USER, DIVISION)
    _completed(chat_store, quiz_status=quiz_status)
    chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        doc_id=DIVISION,
        term="분업/특화",
        attempt=2,
        start_type="relearn",
    )
    state = client.get("/chat/state", headers=HEADERS)
    concepts = client.get("/chat/concepts", headers=HEADERS)
    assert state.status_code == 409
    assert concepts.status_code == 409
    assert state.json() == concepts.json()
    assert state.json()["detail"] == "퀴즈 대기 중에는 진행 중인 세션이 있을 수 없습니다."


def test_other_user_session_is_not_found(client: TestClient, chat_store: SqlChatStore) -> None:
    record = chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        doc_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    own = client.get(f"/chat/sessions/{record.session_id}", headers=HEADERS)
    assert own.status_code == 200
    body = own.json()
    assert body["session_id"] == record.session_id
    assert body["stage"] == STAGE1
    assert body["doc_id"] == DIVISION
    assert body["term"] == "분업/특화"
    assert body["attempt"] == 1
    assert body["start_type"] == "keyword"
    assert body["status"] == "active"
    assert body["completed_at"] is None
    assert "user_id" not in body

    other = client.get(f"/chat/sessions/{record.session_id}", headers={"X-User-Id": "user-2"})
    missing = client.get("/chat/sessions/missing-session", headers=HEADERS)
    assert other.status_code == 404
    assert missing.status_code == 404
    assert other.json() == {"detail": "세션을 찾을 수 없습니다."}
    assert missing.json() == other.json()


def test_state_and_session_require_user_header(client: TestClient) -> None:
    assert client.get("/chat/state").status_code == 401
    assert client.get("/chat/sessions/anything").status_code == 401


def test_another_users_pending_quiz_stays_hidden(
    client: TestClient,
    dev_status: DevConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_failed(USER, DIVISION)
    _completed(chat_store, quiz_status="pending")
    body = client.get("/chat/state", headers={"X-User-Id": "user-2"}).json()
    assert body["mode"] == "normal"
    assert body["locked_concept"] is None


def test_two_active_sessions_are_conflict(client: TestClient, chat_store: SqlChatStore) -> None:
    chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        doc_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    with Session(chat_store._engine) as db:
        db.add(
            ChatSessionRow(
                session_id=str(uuid.uuid4()),
                user_id=USER,
                stage=STAGE1,
                doc_id=DIVISION,
                term="분업/특화",
                attempt=2,
                start_type="relearn",
                status="active",
                created_at=datetime.now(timezone.utc),
                completed_at=None,
            )
        )
        db.commit()
    response = client.get("/chat/state", headers=HEADERS)
    assert response.status_code == 409


def test_newer_passed_quiz_overrides_older_failed(
    client: TestClient,
    dev_status: DevConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_failed(USER, DIVISION)
    older = _completed(chat_store, quiz_status="failed")
    newer = _completed(chat_store, quiz_status="passed", attempt=2)
    with Session(chat_store._engine) as db:
        old_row = db.get(LearningContextRow, older)
        new_row = db.get(LearningContextRow, newer)
        assert old_row is not None and new_row is not None
        old_row.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new_row.created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
        db.commit()
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "quiz_pending"
    assert state["notice"] == QUIZ_NOTICE


def test_session_and_pending_quiz_survive_reopen(status_db) -> None:
    settings = make_settings(status_db, simulate_quiz_status=False)
    first = SqlChatStore(settings)
    record = first.create_session(
        user_id=USER,
        stage=STAGE1,
        doc_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="detected",
        status="completed",
    )
    first.save_learning_context(
        session_id=record.session_id,
        user_id=USER,
        doc_id=DIVISION,
        payload={"doc_id": DIVISION},
        quiz_status="pending",
    )
    first.close()

    second = SqlChatStore(settings)
    try:
        loaded = second.get_session(USER, record.session_id)
        assert loaded == record
        pending = second.get_pending_quiz(USER)
        assert pending is not None
        assert pending.doc_id == DIVISION
        assert pending.stage == STAGE1
        with Session(second._engine) as db:
            context = db.get(LearningContextRow, record.session_id)
            assert context is not None
            assert context.quiz_status == "pending"
            assert context.payload == {"doc_id": DIVISION}
            assert context.user_id == USER
    finally:
        second.close()


def test_chat_tables_are_created(chat_store: SqlChatStore) -> None:
    names = set(inspect(chat_store._engine).get_table_names())
    assert {"chat_sessions", "chat_messages", "learning_contexts"} <= names
