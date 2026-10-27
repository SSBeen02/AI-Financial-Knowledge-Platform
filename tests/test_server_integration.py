import asyncio
import os
from unittest.mock import AsyncMock, Mock

os.environ["LLM_PROVIDER"] = "fake"
os.environ["DEV_MODE"] = "false"
os.environ["CORS_ALLOW_ORIGINS"] = "https://plant-pin-65764387.figma.site"

import httpx
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient
import run_integration as integration
from server_auth import get_verified_user_id

USER = "a4376f94-23b7-46a0-b078-27167ef904a2"


def auth_app(monkeypatch, response):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_PUBLISHABLE_KEY", "test-key")
    app = FastAPI()
    app.state.auth_client = Mock(get=AsyncMock(return_value=response))

    @app.get("/identity")
    async def identity(user=Depends(get_verified_user_id)):
        return {"user": user}
    return app


def test_missing_token_and_user_header_are_rejected(monkeypatch):
    app = auth_app(monkeypatch, None)
    with TestClient(app) as client:
        assert client.get("/identity", headers={"X-User-Id": USER}).status_code == 401
    app.state.auth_client.get.assert_not_called()


@pytest.mark.parametrize("status, expected", [(401, 401), (403, 401), (500, 503)])
def test_auth_failure(monkeypatch, status, expected):
    app = auth_app(monkeypatch, httpx.Response(status))
    with TestClient(app) as client:
        assert client.get("/identity", headers={"Authorization": "Bearer invalid"}).status_code == expected


def test_verified_identity_overrides_spoofed_header(monkeypatch):
    app = auth_app(monkeypatch, httpx.Response(200, json={"id": USER}))
    with TestClient(app) as client:
        result = client.get("/identity", headers={"Authorization": "Bearer verified", "X-User-Id": "someone-else"})
    assert result.json() == {"user": USER}


def test_auth_timeout(monkeypatch):
    app = auth_app(monkeypatch, None)
    app.state.auth_client.get.side_effect = httpx.ConnectTimeout("offline")
    with TestClient(app) as client:
        assert client.get("/identity", headers={"Authorization": "Bearer token"}).status_code == 503


def test_routes_auth_overrides_and_cors(monkeypatch):
    # 다른 테스트의 import 시점에 생성된 설정 캐시와 독립적으로 검증한다.
    settings = integration.deps.get_cached_settings().model_copy(update={
        "cors_allow_origins": "https://plant-pin-65764387.figma.site",
    })
    monkeypatch.setattr(integration.deps, "get_cached_settings", lambda: settings)
    app = integration.create_app()
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    # Include-router internals differ across FastAPI versions; inspect OpenAPI instead.
    paths |= set(app.openapi()["paths"])
    assert "/learning/messages" in paths
    assert "/api/v1/quiz-sets/{id}" in paths
    assert "/game/sync" in paths
    assert "/game/character" in paths
    assert "/diagnostics" in paths and "/diagnostics/current" in paths and "/reports/{id}" in paths
    assert not any(path.startswith("/dev") for path in paths)
    assert app.dependency_overrides[integration.chat_user_id] is get_verified_user_id
    assert app.dependency_overrides[integration.quiz_user_id] is get_verified_user_id
    # No context manager: avoid real production startup/model/DB connections.
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    headers = {"Origin": "https://plant-pin-65764387.figma.site", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,idempotency-key,content-type"}
    assert client.options("/learning/messages", headers=headers).status_code == 200
    headers["Origin"] = "https://app-jlnkxt7eaot76lplf4arwbyvunw6r233ziyqdxgf2ym5koosr7q5.makeproxy-c.figma.site"
    preview = client.options("/learning/messages", headers=headers)
    assert preview.status_code == 200
    assert preview.headers["access-control-allow-origin"] == headers["Origin"]
    health = client.get("/health", headers={"Origin": headers["Origin"]})
    assert health.status_code == 200
    assert health.headers["access-control-allow-origin"] == headers["Origin"]
    headers["Origin"] = "https://1c072bcd-172b-49cd-92a6-1b5ccce474c3-figmacachedpreview.figma.site"
    cached_preview = client.options("/learning/current", headers=headers)
    assert cached_preview.status_code == 200
    assert cached_preview.headers["access-control-allow-origin"] == headers["Origin"]
    health = client.get("/health", headers={"Origin": headers["Origin"]})
    assert health.headers["access-control-allow-origin"] == headers["Origin"]
    headers["Origin"] = "https://untrusted.example"
    assert client.options("/learning/messages", headers=headers).status_code == 400
    headers["Origin"] = "https://app-fake.makeproxy-c.figma.site.evil.example"
    assert client.options("/learning/messages", headers=headers).status_code == 400
    headers["Origin"] = "https://not-a-uuid-figmacachedpreview.figma.site"
    assert client.options("/learning/messages", headers=headers).status_code == 400


def test_startup_connects_callbacks_once_and_disposes(monkeypatch):
    monkeypatch.setattr(integration, "validate_environment", lambda: None)
    for name in ("get_stage_catalog", "get_chat_store", "get_concept_status_service", "get_qdrant_client", "get_dense_encoder", "get_concept_cache", "get_retriever", "get_llm_adapter"):
        monkeypatch.setattr(integration.deps, name, Mock())
    schema = AsyncMock()
    dispose = AsyncMock()
    register = Mock()
    game = Mock()
    prepare = Mock(return_value=game)
    monkeypatch.setattr(integration, "ensure_quiz_schema", schema)
    monkeypatch.setattr(integration, "dispose_quiz_database", dispose)
    monkeypatch.setattr(integration, "register_quiz_integration", register)
    monkeypatch.setattr(integration, "prepare_game_runtime", prepare)
    pretest = Mock()
    monkeypatch.setattr(integration, "prepare_pretest_runtime", Mock(return_value=pretest))
    app = integration.create_app()
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        register.assert_called_once_with(app)
        assert app.state.game_service is game.service
        assert app.state.game_event_source is game.event_source
        assert app.state.pretest_service is pretest.service
    schema.assert_awaited_once()
    dispose.assert_awaited_once()
    prepare.assert_called_once()
    game.close.assert_called_once()
    assert app.state.game_service is None
    pretest.close.assert_called_once()
    assert app.state.pretest_service is None


def test_schema_checks_do_not_create_tables(monkeypatch):
    from app import db
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine

    async def check():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        monkeypatch.setattr(db, "get_engine", lambda: engine)
        monkeypatch.setenv("DB_AUTO_CREATE", "false")
        try:
            with pytest.raises(RuntimeError, match="migration"):
                await db.init_quiz_models()
            async with engine.connect() as connection:
                assert await connection.run_sync(lambda conn: inspect(conn).get_table_names()) == []
            monkeypatch.setenv("DB_AUTO_CREATE", "true")
            await db.init_quiz_models()
            monkeypatch.setenv("DB_AUTO_CREATE", "false")
            await db.init_quiz_models()
        finally:
            await engine.dispose()
    asyncio.run(check())
