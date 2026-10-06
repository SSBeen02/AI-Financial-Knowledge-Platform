"""RAG 챗봇 모듈을 로컬에서 단독 실행하는 FastAPI 앱."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from chatbot.config import Settings
from chatbot.dev_tools import router as dev_router
from chatbot.dev_ui import DEV_CHAT_HTML
from chatbot.deps import (
    get_cached_settings,
    get_chat_store,
    get_concept_cache,
    get_concept_status_service,
    get_dense_encoder,
    get_llm_adapter,
    get_qdrant_client,
    get_retriever,
    get_quiz_service,
    get_stage_catalog,
)
from chatbot.router import router as chat_router
from chatbot.errors import install_learning_error_handlers


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """무거운 검색 의존성과 개념 캐시를 프로세스 시작 시 한 번 준비한다."""
    get_cached_settings()
    get_stage_catalog()
    get_chat_store()
    get_concept_status_service()
    get_qdrant_client()
    get_dense_encoder()
    get_concept_cache()
    get_retriever()
    get_llm_adapter()
    get_quiz_service()
    yield


def health() -> dict[str, str]:
    return {"status": "ok"}


def dev_chat() -> HTMLResponse:
    return HTMLResponse(DEV_CHAT_HTML)


def create_app(settings: Settings | None = None) -> FastAPI:
    """설정에 따라 개발 도구를 포함한 단독 실행 앱을 만든다."""
    resolved = settings or get_cached_settings()
    application = FastAPI(
        title="나의 경세학당 RAG 챗봇",
        version="1.0.0",
        lifespan=lifespan,
    )
    install_learning_error_handlers(application)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(chat_router)
    application.add_api_route("/health", health, methods=["GET"], tags=["system"])
    if resolved.dev_enable_tools:
        application.include_router(dev_router)
        application.add_api_route(
            "/dev/chat",
            dev_chat,
            methods=["GET"],
            response_class=HTMLResponse,
            include_in_schema=False,
        )
    return application


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main_dev:app", host="127.0.0.1", port=8000, reload=False)
