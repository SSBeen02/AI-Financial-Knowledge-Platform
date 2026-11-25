"""Independent module engines must not multiply session connections during rollout."""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import TimeoutError
from sqlalchemy.pool import QueuePool


@pytest.mark.parametrize("module_name", ["chat", "learning", "quiz", "pretest", "game"])
def test_postgres_engine_cannot_open_overflow_connections(monkeypatch, module_name):
    from app import db
    from chatbot import learning_management, store
    from game import integration as game
    from pretest import integration as pretest

    class Captured(Exception):
        pass

    engines = []
    def capture(url, **options):
        # Exercise the production pool options with local DBAPI connections only.
        for key in ("connect_args", "json_serializer", "json_deserializer", "hide_parameters"):
            options.pop(key, None)
        engine = create_engine("sqlite://", poolclass=QueuePool, **options)
        engines.append(engine)
        raise Captured()

    url = "postgresql+psycopg://unused:unused@localhost/unused"
    modules = {"chat": store, "learning": learning_management,
               "quiz": db, "pretest": pretest, "game": game}
    monkeypatch.setattr(modules[module_name], "create_async_engine" if module_name == "quiz" else "create_engine", capture)
    monkeypatch.setenv("CHAT_DB_URL", url)
    monkeypatch.setenv("GAME_DATABASE_URL", url)
    monkeypatch.setenv("PRETEST_ENABLED", "true")
    monkeypatch.setenv("GAME_ENABLED", "true")
    monkeypatch.setenv("LLM_REPORT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "unused")
    monkeypatch.setenv("QUIZ_DATABASE_URL", "postgresql+asyncpg://unused:unused@localhost/unused")
    if module_name == "quiz":
        monkeypatch.setattr(db, "_engine", None)
    calls = {
        "chat": lambda: store.SqlChatStore(SimpleNamespace(chat_db_url=url)),
        "learning": lambda: learning_management.create_database_engine(url),
        "quiz": db.get_engine,
        "pretest": pretest.prepare_pretest_runtime,
        "game": lambda: game.prepare_game_runtime(None),
    }
    with pytest.raises(Captured):
        calls[module_name]()
    engine = engines[0]
    try:
        assert engine.pool.size() == 1
        assert engine.pool.timeout() == 15
        # Avoid waiting 15 seconds while proving a second checkout cannot overflow.
        engine.pool._timeout = 0.01
        with engine.connect() as first:
            assert first.exec_driver_sql("select 1").scalar() == 1
            with pytest.raises(TimeoutError):
                engine.connect()
        with engine.connect() as returned:
            assert returned.exec_driver_sql("select 1").scalar() == 1
    finally:
        engine.dispose()
