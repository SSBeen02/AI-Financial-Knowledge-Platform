"""외부 서비스 없이 실제 퀴즈 콜백→학습 이벤트→게임 API 경로를 검증한다."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

import run_integration as integration
from app.services import learning_callbacks
from chatbot.config import Settings
from chatbot.integrations import SqlConceptStatusService
from chatbot.store import SqlChatStore
from game.integration import LearningEventSource, build_game_runtime, prepare_game_runtime, validate_game_access
from game.models import Base
from server_auth import get_verified_user_id


def test_runtime_does_not_create_missing_schema_and_disabled_mode_does_not_connect(monkeypatch):
    engine = create_engine("sqlite://")
    source = Mock()
    source.get_unprocessed_events = lambda *, user_id, limit: []
    try:
        with pytest.raises(RuntimeError, match="migration"):
            build_game_runtime(engine, source)
        assert inspect(engine).get_table_names() == []
        monkeypatch.setenv("GAME_ENABLED", "false")
        monkeypatch.setenv("GAME_DATABASE_URL", "invalid")
        assert prepare_game_runtime(source) is None
        with pytest.raises(RuntimeError, match="user_id"):
            LearningEventSource(type("OldService", (), {"get_unprocessed_events": lambda self, limit=100: []})())
    finally:
        engine.dispose()


def test_unsafe_browser_permissions_or_missing_rls_prevent_startup():
    from contextlib import nullcontext
    rows = [dict(relname=name, relrowsecurity=True, anon_access=False,
                 browser_write=False, user_read=True) for name in Base.metadata.tables]
    connection = Mock()
    connection.execute.return_value.mappings.return_value.all.return_value = rows
    engine = Mock()
    engine.connect.return_value = nullcontext(connection)
    validate_game_access(engine)
    for field, unsafe in [("relrowsecurity", False), ("anon_access", True), ("browser_write", True)]:
        original = rows[0][field]
        rows[0][field] = unsafe
        engine.connect.return_value = nullcontext(connection)
        with pytest.raises(RuntimeError, match="RLS"):
            validate_game_access(engine)
        rows[0][field] = original


def test_real_quiz_callback_learning_events_and_game_api_are_user_scoped(tmp_path, monkeypatch):
    catalog = Path(__file__).resolve().parents[1] / "rag/chatbot_module/data/stages.json"
    settings = Settings(_env_file=None, llm_provider="fake", llm_model="test",
                        chat_db_url=f"sqlite:///{(tmp_path / 'learning.db').as_posix()}",
                        stages_json_path=catalog, db_auto_create=True)
    learning_store = SqlChatStore(settings)
    learning = SqlConceptStatusService(settings)
    game_engine = create_engine(f"sqlite:///{(tmp_path / 'game.db').as_posix()}")
    Base.metadata.create_all(game_engine)
    runtime = build_game_runtime(game_engine, learning)
    learning_callbacks.configure_learning_callbacks(store_provider=lambda: learning_store,
                                                    status_provider=lambda: learning)
    try:
        for user in ("user-a", "user-b"):
            learning.mark_in_progress(user, "sisa_1281", "stage1")
            session = learning_store.create_session(user_id=user, stage="stage1", concept_id="sisa_1281",
                term="분업/특화", attempt=1, start_type="keyword")
            learning_store.complete_session_with_context(user_id=user, session_id=session.session_id,
                concept_id="sisa_1281", idempotency_key=f"complete-{user}",
                payload={"session_id": session.session_id}, completed_at=datetime.now(timezone.utc))
            asyncio.run(learning_callbacks.report_quiz_result(user_id=user, submission_id=f"submission-{user}",
                session_id=session.session_id, concept_id="sisa_1281", stage_id="stage1", correct_count=2, passed=True))
        assert len(learning.get_unprocessed_events(user_id="user-a")) == 1
        assert len(learning.get_unprocessed_events(user_id="user-b")) == 1
        app = integration.create_app()
        app.state.game_service, app.state.game_event_source = runtime.service, runtime.event_source
        app.dependency_overrides[get_verified_user_id] = lambda: "user-a"
        # 운영 lifespan을 실행하지 않아 실제 DB·LLM·Qdrant에 연결하지 않는다.
        client = TestClient(app)
        assert client.post("/game/character", json={"name": "학당"}).status_code == 200
        response = client.post("/game/sync")
        assert response.status_code == 200
        data = response.json()
        assert data["game_state"]["coin_balance"] == 10
        assert data["game_state"]["passed_concept_count"] == 1
        assert data["game_state"]["stage_progress"] == 3
        assert not data["retry_pending"]
        assert learning.get_unprocessed_events(user_id="user-a") == []
        assert len(learning.get_unprocessed_events(user_id="user-b")) == 1
        assert client.post("/game/sync").json()["game_state"]["coin_balance"] == 10
        assert learning.get_concept_status("user-a", "sisa_1281", "stage1") == "passed"
    finally:
        learning_callbacks.configure_learning_callbacks(store_provider=None, status_provider=None)
        runtime.close()
        learning.close()
        learning_store.close()
