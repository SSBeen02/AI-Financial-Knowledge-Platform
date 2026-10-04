"""RAG 챗봇 모듈을 로컬에서 단독 실행하는 FastAPI 앱."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from chatbot.deps import (
    get_cached_settings,
    get_chat_store,
    get_concept_cache,
    get_concept_status_service,
    get_dense_encoder,
    get_llm_adapter,
    get_qdrant_client,
    get_retriever,
    get_stage_catalog,
)
from chatbot.router import router as chat_router


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
    yield


app = FastAPI(
    title="나의 경세학당 RAG 챗봇",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(chat_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main_dev:app", host="127.0.0.1", port=8000, reload=False)
