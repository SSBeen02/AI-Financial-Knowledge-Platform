"""FastAPI 의존성.

임베딩 모델, Qdrant 클라이언트, 개념 캐시는 처음 꺼낼 때 한 번만 만든다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from chatbot.concepts import StageCatalog, load_stage_catalog
from chatbot.config import Settings, get_settings
from chatbot.integrations import ConceptStatusService, SqlConceptStatusService
from chatbot.llm import FakeLLMAdapter, LLMAdapter, OpenAIAdapter, UpstageAdapter
from chatbot.retrieval import ConceptCache, Retriever
from chatbot.quiz import DevQuizService, QuizService
from chatbot.store import ChatStore, SqlChatStore

_status_service: SqlConceptStatusService | None = None
_chat_store: SqlChatStore | None = None
_qdrant: Any | None = None
_dense: Any | None = None
_sparse: Any | None = None
_concept_cache: ConceptCache | None = None
_retriever: Retriever | None = None
_llm_adapter: LLMAdapter | None = None
_quiz_service: QuizService | None = None


@lru_cache
def get_cached_settings() -> Settings:
    return get_settings()


@lru_cache
def get_stage_catalog() -> StageCatalog:
    return load_stage_catalog(get_cached_settings().stages_json_path)


def get_concept_status_service() -> ConceptStatusService:
    global _status_service
    if _status_service is None:
        _status_service = SqlConceptStatusService(get_cached_settings())
    return _status_service


def get_chat_store() -> ChatStore:
    global _chat_store
    if _chat_store is None:
        _chat_store = SqlChatStore(get_cached_settings())
    return _chat_store


def get_qdrant_client() -> Any:
    global _qdrant
    if _qdrant is None:
        from qdrant_client import QdrantClient

        settings = get_cached_settings()
        _qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    return _qdrant


def get_dense_encoder() -> Any:
    global _dense
    if _dense is None:
        from chatbot.embedding_cache import CachedQueryEncoder
        from rag_common import DenseEncoder

        _dense = CachedQueryEncoder(DenseEncoder(get_cached_settings().dense_model))
    return _dense


def get_sparse_encoder() -> Any:
    global _sparse
    if _sparse is None:
        from chatbot.fss_sparse import FssSparseEncoder

        _sparse = FssSparseEncoder()
    return _sparse


def get_concept_cache() -> ConceptCache:
    global _concept_cache
    if _concept_cache is None:
        settings = get_cached_settings()
        _concept_cache = ConceptCache(
            get_qdrant_client(),
            settings.qdrant_collection,
            get_stage_catalog().by_concept,
        )
    return _concept_cache


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        settings = get_cached_settings()
        sparse = get_sparse_encoder() if any(
            profile["mode"] != "dense" for profile in settings.search_profiles.values()
        ) else None
        _retriever = Retriever(get_qdrant_client(), get_dense_encoder(), settings, sparse=sparse)
    return _retriever


def get_llm_adapter() -> LLMAdapter:
    global _llm_adapter
    if _llm_adapter is None:
        settings = get_cached_settings()
        if settings.llm_provider == "fake":
            _llm_adapter = FakeLLMAdapter(settings)
        elif settings.llm_provider == "upstage":
            _llm_adapter = UpstageAdapter(settings)
        else:
            _llm_adapter = OpenAIAdapter(settings)
    return _llm_adapter


def get_quiz_service() -> QuizService:
    global _quiz_service
    if _quiz_service is None:
        _quiz_service = DevQuizService(get_cached_settings())
    return _quiz_service


WARMUP_QUERY = "복리이자란 무엇인가"


def warm_up_retrieval() -> float | None:
    """서버 시작 시 임베딩·Kiwi·Qdrant 연결을 한 번 실행해 첫 요청의 지연을 줄인다.

    LLM 호출과 DB 저장은 하지 않는다. 실패해도 서버 기동은 계속한다.
    `CHATBOT_WARMUP=false`이면 건너뛴다. 반환값은 소요 초(건너뛰거나 실패하면 None).
    """
    import logging
    import os
    from time import perf_counter

    logger = logging.getLogger("uvicorn.error")
    _log_cpu_threads(logger)
    if os.getenv("CHATBOT_WARMUP", "true").strip().lower() in {"0", "false", "no", "off"}:
        logger.info("chatbot_warmup skipped (CHATBOT_WARMUP=false)")
        return None
    started = perf_counter()
    try:
        get_retriever().search(WARMUP_QUERY)
    except Exception:
        logger.warning("chatbot_warmup failed; server continues", exc_info=True)
        return None
    finally:
        clear = getattr(get_dense_encoder(), "clear", None)
        if callable(clear):
            clear()  # 워밍업 질문은 질문 캐시에 남기지 않는다.
    elapsed = perf_counter() - started
    logger.info("chatbot_warmup done elapsed_s=%.2f", elapsed)
    return elapsed


def _log_cpu_threads(logger: Any) -> None:
    import os

    try:
        import torch

        torch_threads: Any = torch.get_num_threads()
    except Exception:
        torch_threads = "unavailable"
    logger.info(
        "chatbot_runtime cpu_count=%s torch_threads=%s OMP_NUM_THREADS=%s MKL_NUM_THREADS=%s",
        os.cpu_count(), torch_threads,
        os.getenv("OMP_NUM_THREADS", "unset"), os.getenv("MKL_NUM_THREADS", "unset"),
    )
