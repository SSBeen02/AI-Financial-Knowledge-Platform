from __future__ import annotations

import asyncio

import main_dev
from fastapi.middleware.cors import CORSMiddleware

from chatbot.config import Settings


def test_main_dev_exposes_docs_health_and_chat_routes() -> None:
    schema = main_dev.app.openapi()
    paths = set(schema["paths"])
    assert main_dev.app.docs_url == "/docs"
    assert "/health" in paths
    assert "/learning/messages" in paths
    assert "/learning/messages/stream" in paths
    assert "/learning/current" in paths
    assert not any(path.startswith("/chat") for path in paths)
    state_parameters = schema["paths"]["/learning/current"]["get"]["parameters"]
    assert any(
        parameter["in"] == "header" and parameter["name"] == "x-user-id"
        for parameter in state_parameters
    )


def test_lifespan_preloads_each_process_dependency_once(monkeypatch) -> None:
    names = [
        "get_cached_settings",
        "get_stage_catalog",
        "get_chat_store",
        "get_concept_status_service",
        "get_qdrant_client",
        "get_dense_encoder",
        "get_concept_cache",
        "get_retriever",
        "get_llm_adapter",
        "get_quiz_service",
    ]
    calls: list[str] = []
    for name in names:
        monkeypatch.setattr(main_dev, name, lambda name=name: calls.append(name))

    async def run_lifespan() -> None:
        async with main_dev.lifespan(main_dev.app):
            pass

    asyncio.run(run_lifespan())
    assert calls == names


def test_cors_allows_configured_frontend_origin() -> None:
    application = main_dev.create_app(
        Settings(
            _env_file=None,
            llm_provider="fake",
            cors_allow_origins="http://localhost:5173,http://localhost:3000",
        )
    )
    middleware = next(
        item for item in application.user_middleware if item.cls is CORSMiddleware
    )
    assert middleware.kwargs["allow_origins"] == [
        "http://localhost:5173",
        "http://localhost:3000",
    ]
