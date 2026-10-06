from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chatbot.integrations import SqlConceptStatusService
from chatbot.config import Settings
from chatbot.deps import get_cached_settings
from chatbot.learning_management import DatabaseSchemaNotReadyError
from chatbot.store import LearningSessionRow, LearningContextRow, SqlChatStore
from tests.conftest import make_settings
from tests.test_concepts import DIVISION, HEADERS, USER

STAGE1 = "stage1"
NOTICE = "지금 분업/특화 개념을 학습 중이오. 이 개념을 통과해야 다음 개념으로 넘어갈 수 있소."
ACTIVE_NOTICE = "지금 분업/특화 개념을 학습 중이오. 학습을 마치고 퀴즈를 통과하면 다음 개념을 고를 수 있소."
QUIZ_NOTICE = "현재 분업/특화 개념의 퀴즈 결과를 기다리는 중이오."


def test_chat_store_requires_migration_when_auto_create_is_disabled(tmp_path) -> None:
    settings = Settings(
        _env_file=None,
        llm_model="gpt-test",
        chat_db_url=f"sqlite:///{(tmp_path / 'empty.db').as_posix()}",
        db_auto_create=False,
    )
    with pytest.raises(DatabaseSchemaNotReadyError, match="001 → 002 → 003"):
        SqlChatStore(settings)


def _modes(client: TestClient) -> tuple[dict, dict]:
    state = client.get("/learning/current", headers=HEADERS).json()
    concepts = client.get("/learning/concepts", headers=HEADERS).json()
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
        concept_id=DIVISION,
        term="분업/특화",
        attempt=attempt,
        start_type=start_type,  # type: ignore[arg-type]
        status="completed",
    )
    store.save_learning_context(
        session_id=record.session_id,
        user_id=user_id,
        concept_id=DIVISION,
        payload={"concept_id": DIVISION},
        quiz_status=quiz_status,  # type: ignore[arg-type]
    )
    return record.session_id


def test_mode_priority_is_pending_then_relearn_then_normal(
    client: TestClient,
    dev_status: SqlConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "normal"
    assert state["active_session"] is None
    assert state["locked_concept"] is None
    assert state["notice"] is None
    assert state["complete_hint"] == (
        "아직 배우고 있는 개념이 없소. 아래 키워드를 눌러 학습을 시작해 보시오."
    )
    assert state["learning_guide"].startswith("아래 키워드를 눌러")
    assert state["status_labels"] == {
        "not_started": "미학습",
        "in_progress": "학습중",
        "passed": "통과",
    }
    assert state["progress"]["stage_id"] == "stage1"
    assert state["progress"]["total_count"] == 30

    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "normal"
    assert state["locked_concept"]["concept_id"] == DIVISION
    assert state["notice"] == concepts["notice"] == ACTIVE_NOTICE
    assert state["quick_prompts"][0] == "분업/특화에 대해 더 자세히 알려줘"
    assert concepts["concepts"][0]["concept_id"] == "sisa_1963"

    session_id = _completed(chat_store, quiz_status="failed")
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "relearn"
    assert state["locked_concept"] == concepts["locked_concept"]
    assert state["locked_concept"]["concept_id"] == DIVISION
    assert state["notice"] == concepts["notice"] == NOTICE
    assert concepts["suggested_message"] == "분업/특화에 대해 다시 알려줘"
    assert state["active_session"] is None

    chat_store.set_quiz_status(USER, session_id, "pending")
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "quiz_pending"
    assert state["locked_concept"]["concept_id"] == concepts["locked_concept"]["concept_id"] == DIVISION
    assert state["notice"] == concepts["notice"] == QUIZ_NOTICE
    assert concepts["suggested_message"] is None
    assert concepts["concepts"][0]["concept_id"] == "sisa_1963"
    assert state["active_session"] is None
    chat_store.set_quiz_status(USER, session_id, "passed")
    state, concepts = _modes(client)
    assert dev_status.get_in_progress_concept(USER, STAGE1) is not None
    assert state["mode"] == concepts["mode"] == "quiz_pending"
    assert state["notice"] == QUIZ_NOTICE
    assert concepts["suggested_message"] is None

    chat_store.set_quiz_status(USER, session_id, "failed")
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "relearn"
    assert state["notice"] == NOTICE


def test_modern_tone_is_used_for_relearn_notice(
    client: TestClient,
    dev_status: SqlConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    client.app.dependency_overrides[get_cached_settings] = lambda: Settings(
        _env_file=None, llm_model="gpt-test", chat_tone="modern"
    )
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    _completed(chat_store, quiz_status="failed")

    state, concepts = _modes(client)

    expected = "지금 분업/특화 개념을 학습 중이에요. 이 개념을 통과해야 다음 개념으로 넘어갈 수 있어요."
    assert state["notice"] == concepts["notice"] == expected


def test_in_progress_display_label_is_fixed_to_learning(
    client: TestClient,
    dev_status: SqlConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    _completed(chat_store, quiz_status="failed")

    state, concepts = _modes(client)

    assert state["notice"] == concepts["notice"] == NOTICE
    assert state["status_labels"]["in_progress"] == "학습중"


def test_state_includes_the_active_relearn_session(
    client: TestClient,
    dev_status: SqlConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    _completed(chat_store, quiz_status="failed")
    record = chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        concept_id=DIVISION,
        term="분업/특화",
        attempt=2,
        start_type="relearn",
    )
    body = client.get("/learning/current", headers=HEADERS).json()
    assert body["mode"] == "relearn"
    assert body["active_session"]["session_id"] == record.session_id
    assert body["active_session"]["attempt"] == 2
    assert body["active_session"]["start_type"] == "relearn"
    assert body["active_session"]["status"] == "active"
    assert body["active_session"]["completed_at"] is None
    assert body["complete_hint"] is None
    assert "user_id" not in body["active_session"]


def test_learning_without_quiz_record_stays_normal(
    client: TestClient,
    dev_status: SqlConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    record = chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        concept_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    state, concepts = _modes(client)
    assert state["mode"] == concepts["mode"] == "normal"
    assert state["active_session"]["session_id"] == record.session_id
    assert state["locked_concept"]["concept_id"] == DIVISION
    assert state["notice"] == concepts["notice"] == ACTIVE_NOTICE
    assert state["quick_prompts"] == [
        "분업/특화에 대해 더 자세히 알려줘",
        "분업/특화의 예시를 더 들어줘",
        "분업/특화과 비슷한 개념은 뭐야?",
    ]


@pytest.mark.parametrize("quiz_status", ["pending", "passed"])
def test_quiz_pending_cannot_have_active_session(
    client: TestClient,
    dev_status: SqlConceptStatusService,
    chat_store: SqlChatStore,
    quiz_status: str,
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    _completed(chat_store, quiz_status=quiz_status)
    chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        concept_id=DIVISION,
        term="분업/특화",
        attempt=2,
        start_type="relearn",
    )
    state = client.get("/learning/current", headers=HEADERS)
    concepts = client.get("/learning/concepts", headers=HEADERS)
    assert state.status_code == 409
    assert concepts.status_code == 409
    assert state.json()["code"] == concepts.json()["code"] == "conflict"
    assert state.json()["message"] == concepts.json()["message"]
    assert state.json()["message"] == "퀴즈 대기 중에는 진행 중인 세션이 있을 수 없습니다."
    assert state.headers["X-Request-ID"] == state.json()["request_id"]


def test_other_user_session_is_not_found(client: TestClient, chat_store: SqlChatStore) -> None:
    record = chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        concept_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    own = client.get(f"/learning/sessions/{record.session_id}", headers=HEADERS)
    assert own.status_code == 200
    body = own.json()
    assert body["session_id"] == record.session_id
    assert body["stage"] == STAGE1
    assert body["concept_id"] == DIVISION
    assert body["term"] == "분업/특화"
    assert body["attempt"] == 1
    assert body["start_type"] == "keyword"
    assert body["status"] == "active"
    assert body["completed_at"] is None
    assert "user_id" not in body

    other = client.get(f"/learning/sessions/{record.session_id}", headers={"X-User-Id": "user-2"})
    missing = client.get("/learning/sessions/missing-session", headers=HEADERS)
    assert other.status_code == 404
    assert missing.status_code == 404
    assert other.json()["code"] == missing.json()["code"] == "not_found"
    assert other.json()["message"] == missing.json()["message"] == "세션을 찾을 수 없습니다."
    assert other.headers["X-Request-ID"] == other.json()["request_id"]


def test_state_and_session_require_user_header(client: TestClient) -> None:
    assert client.get("/learning/current").status_code == 401
    assert client.get("/learning/sessions/anything").status_code == 401


def test_another_users_pending_quiz_stays_hidden(
    client: TestClient,
    dev_status: SqlConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
    _completed(chat_store, quiz_status="pending")
    body = client.get("/learning/current", headers={"X-User-Id": "user-2"}).json()
    assert body["mode"] == "normal"
    assert body["locked_concept"] is None


def test_database_rejects_two_active_sessions(chat_store: SqlChatStore) -> None:
    chat_store.create_session(
        user_id=USER,
        stage=STAGE1,
        concept_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    with Session(chat_store._engine) as db:
        db.add(
            LearningSessionRow(
                session_id=str(uuid.uuid4()),
                user_id=USER,
                stage=STAGE1,
                concept_id=DIVISION,
                term="분업/특화",
                attempt=2,
                start_type="relearn",
                status="active",
                created_at=datetime.now(timezone.utc),
                completed_at=None,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_newer_passed_quiz_overrides_older_failed(
    client: TestClient,
    dev_status: SqlConceptStatusService,
    chat_store: SqlChatStore,
) -> None:
    dev_status.mark_in_progress(USER, DIVISION, STAGE1)
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
        concept_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="detected",
        status="completed",
    )
    first.save_learning_context(
        session_id=record.session_id,
        user_id=USER,
        concept_id=DIVISION,
        payload={"concept_id": DIVISION},
        quiz_status="pending",
    )
    first.close()

    second = SqlChatStore(settings)
    try:
        loaded = second.get_session(USER, record.session_id)
        assert loaded == record
        pending = second.get_pending_quiz(USER)
        assert pending is not None
        assert pending.concept_id == DIVISION
        assert pending.stage == STAGE1
        with Session(second._engine) as db:
            context = db.get(LearningContextRow, record.session_id)
            assert context is not None
            assert context.quiz_status == "pending"
            assert context.payload == {"concept_id": DIVISION}
            assert context.user_id == USER
    finally:
        second.close()


def test_chat_tables_are_created(chat_store: SqlChatStore) -> None:
    names = set(inspect(chat_store._engine).get_table_names())
    assert {
        "learning_sessions",
        "learning_messages",
        "learning_contexts",
        "learning_completion_requests",
    } <= names


def test_legacy_chat_tables_and_doc_id_data_are_preserved(status_db) -> None:
    settings = make_settings(status_db, simulate_quiz_status=False)
    engine = create_engine(settings.chat_db_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE chat_sessions ("
            "session_id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, stage VARCHAR NOT NULL, "
            "doc_id VARCHAR NOT NULL, term VARCHAR NOT NULL, attempt INTEGER NOT NULL, "
            "start_type VARCHAR NOT NULL, status VARCHAR NOT NULL, created_at DATETIME NOT NULL, "
            "completed_at DATETIME)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE chat_messages ("
            "message_id VARCHAR PRIMARY KEY, session_id VARCHAR, user_id VARCHAR NOT NULL, "
            "role VARCHAR NOT NULL, content VARCHAR NOT NULL, is_related BOOLEAN, band VARCHAR, "
            "top_score FLOAT, sources JSON, latency_ms INTEGER, created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE learning_contexts ("
            "session_id VARCHAR PRIMARY KEY, user_id VARCHAR NOT NULL, doc_id VARCHAR NOT NULL, "
            "quiz_status VARCHAR NOT NULL, payload JSON NOT NULL, created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO chat_sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-session",
                USER,
                STAGE1,
                DIVISION,
                "분업/특화",
                1,
                "keyword",
                "completed",
                "2026-01-01 00:00:00",
                "2026-01-01 00:01:00",
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-message",
                "legacy-session",
                USER,
                "assistant",
                "설명",
                1,
                "high",
                0.7,
                '[{"doc_id":"sisa_1281","term":"분업/특화","score":0.7,"collection":"sisa_terms","label":"사전"}]',
                10,
                "2026-01-01 00:00:30",
            ),
        )
        connection.exec_driver_sql(
            "INSERT INTO learning_contexts VALUES (?, ?, ?, ?, ?, ?)",
            (
                "legacy-session",
                USER,
                DIVISION,
                "pending",
                '{"concept":{"doc_id":"sisa_1281","status":"in_progress"}}',
                "2026-01-01 00:01:00",
            ),
        )
    engine.dispose()

    store = SqlChatStore(settings)
    try:
        names = set(inspect(store._engine).get_table_names())
        assert "chat_sessions" not in names
        assert "chat_messages" not in names
        assert {"learning_sessions", "learning_messages"} <= names
        assert store.get_session(USER, "legacy-session").concept_id == DIVISION  # type: ignore[union-attr]
        message = store.get_session_messages(USER, "legacy-session")[0]
        assert message.sources is not None
        assert message.sources[0]["concept_id"] == DIVISION
        context = store.get_learning_context(USER, "legacy-session")
        assert context is not None
        assert context.concept_id == DIVISION
        assert context.payload["concept"] == {
            "concept_id": DIVISION,
            "status": "in_progress",
        }
    finally:
        store.close()
