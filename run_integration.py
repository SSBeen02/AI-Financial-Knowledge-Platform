"""Cloudtype entry point: run from the repository root with one worker."""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHATBOT_ROOT = ROOT / "rag" / "chatbot_module"
QUIZ_ROOT = ROOT / "quiz-upload"
for module_root in (CHATBOT_ROOT, QUIZ_ROOT):
    sys.path.insert(0, str(module_root))

# Deployment uses process variables only; nested development .env files are ignored.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
catalog = Path(os.getenv("STAGES_JSON_PATH", "data/stages.json"))
if not catalog.is_absolute():
    os.environ["STAGES_JSON_PATH"] = str((CHATBOT_ROOT / catalog).resolve())

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints.quizzes import router as quiz_router
from app.db import dispose_quiz_database, ensure_quiz_schema
from app.errors import QuizAPIError, quiz_api_error_handler, validation_error_handler
from app.services.team_quiz import register_quiz_integration
from chatbot import deps
from chatbot.errors import install_learning_error_handlers
from chatbot.integrations import get_current_user_id as chat_user_id
from chatbot.router import router as chat_router
from dependencies import get_current_user_id as quiz_user_id
from server_auth import auth_settings, get_verified_user_id


def validate_environment() -> None:
    for name in ("QUIZ_DATABASE_URL", "CHAT_DB_URL", "OPENAI_API_KEY", "CORS_ALLOW_ORIGINS"):
        if not os.getenv(name, "").strip():
            raise RuntimeError(f"{name} 환경변수가 필요합니다.")
    if not os.environ["QUIZ_DATABASE_URL"].startswith("postgresql+asyncpg://"):
        raise RuntimeError("QUIZ_DATABASE_URL은 postgresql+asyncpg:// 형식이어야 합니다.")
    if not os.environ["CHAT_DB_URL"].startswith("postgresql+psycopg://"):
        raise RuntimeError("CHAT_DB_URL은 postgresql+psycopg:// 형식이어야 합니다.")
    for name in ("DB_AUTO_CREATE", "DEV_ENABLE_TOOLS", "DEV_MODE", "DEV_SIMULATE_QUIZ_GENERATION_FAILURE"):
        if os.getenv(name, "false").strip().lower() != "false":
            raise RuntimeError(f"통합 배포에서는 {name}=false로 설정하세요.")
    if "*" in deps.get_cached_settings().cors_origins:
        raise RuntimeError("CORS_ALLOW_ORIGINS에는 실제 프론트 origin을 지정하세요.")
    auth_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_environment()
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        app.state.auth_client = client
        try:
            deps.get_stage_catalog()
            deps.get_chat_store()
            deps.get_concept_status_service()
            await ensure_quiz_schema()
            register_quiz_integration(app)
            deps.get_qdrant_client()
            deps.get_dense_encoder()
            deps.get_concept_cache()
            deps.get_retriever()
            deps.get_llm_adapter()
            yield
        finally:
            await dispose_quiz_database()


def create_app() -> FastAPI:
    # Explicitly disable pydantic-settings' independent dotenv reader as well.
    settings = deps.get_cached_settings()
    application = FastAPI(title="경세학당 챗봇 + 퀴즈 통합", lifespan=lifespan)
    install_learning_error_handlers(application)
    learning_validation = application.exception_handlers[RequestValidationError]

    async def validation(request, exc):
        if request.url.path.startswith("/api/v1/"):
            return await validation_error_handler(request, exc)
        return await learning_validation(request, exc)

    application.add_exception_handler(QuizAPIError, quiz_api_error_handler)
    application.add_exception_handler(RequestValidationError, validation)
    application.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins,
        allow_credentials=True, allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    application.dependency_overrides[chat_user_id] = get_verified_user_id
    application.dependency_overrides[quiz_user_id] = get_verified_user_id
    application.include_router(chat_router)
    application.include_router(quiz_router)

    @application.get("/health", tags=["system"])
    def health():
        return {"status": "ok"}

    return application


app = create_app()
