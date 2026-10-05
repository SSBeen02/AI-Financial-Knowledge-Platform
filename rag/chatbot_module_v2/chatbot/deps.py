"""FastAPI 의존성.

임베딩 모델, Qdrant 클라이언트, 개념 캐시는 처음 꺼낼 때 한 번만 만든다.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from chatbot.concepts import StageCatalog, load_stage_catalog
from chatbot.config import Settings, get_settings
from chatbot.integrations import ConceptStatusService, DevConceptStatusService
from chatbot.llm import LLMAdapter, OpenAIAdapter
from chatbot.retrieval import ConceptCache, Retriever
from chatbot.store import ChatStore, SqlChatStore

_status_service: DevConceptStatusService | None = None
_chat_store: SqlChatStore | None = None
_qdrant: Any | None = None
_dense: Any | None = None
_concept_cache: ConceptCache | None = None
_retriever: Retriever | None = None
_llm_adapter: LLMAdapter | None = None


@lru_cache
def get_cached_settings() -> Settings:
    return get_settings()


@lru_cache
def get_stage_catalog() -> StageCatalog:
    return load_stage_catalog(get_cached_settings().stages_json_path)


def get_concept_status_service() -> ConceptStatusService:
    global _status_service
    if _status_service is None:
        _status_service = DevConceptStatusService(get_cached_settings())
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
        from rag_common import DenseEncoder

        _dense = DenseEncoder(get_cached_settings().dense_model)
    return _dense


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
        _retriever = Retriever(get_qdrant_client(), get_dense_encoder(), get_cached_settings())
    return _retriever


def get_llm_adapter() -> LLMAdapter:
    global _llm_adapter
    if _llm_adapter is None:
        _llm_adapter = OpenAIAdapter(get_cached_settings())
    return _llm_adapter
