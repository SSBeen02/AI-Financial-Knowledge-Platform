"""Qdrant와 임베딩 모델이 있을 때만 실행하는 검색 확인."""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from chatbot.concepts import load_stage_catalog
from chatbot.config import Settings
from chatbot.retrieval import ConceptCache, Retriever, judge_band
from rag_common import DenseEncoder


def _live_settings() -> Settings | None:
    # integration 테스트만 실제 .env와 OS 환경변수를 사용한다.
    settings = Settings(_env_file=".env")
    if not settings.qdrant_url or not settings.qdrant_api_key:
        return None
    return settings


@pytest.mark.integration
def test_live_opportunity_cost_search() -> None:
    settings = _live_settings()
    if settings is None:
        pytest.skip("Qdrant 접속 정보가 없습니다.")
    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    dense = DenseEncoder(settings.dense_model)
    result = Retriever(client, dense, settings).search("기회비용이 뭐야?")
    assert result.sources
    assert len(result.sources) <= 3
    assert result.band == judge_band(result.top_score, high=settings.band_high, low=settings.band_low)
    assert result.top_score == result.sources[0].score
    assert result.sources[0].collection == settings.qdrant_collection
    catalog = load_stage_catalog(settings.stages_json_path)
    cache = ConceptCache(client, settings.qdrant_collection, catalog.by_concept)
    cached = cache.get(result.sources[0].concept_id)
    assert cached is not None
    assert cached.concept_id == result.sources[0].concept_id
    assert cached.term == result.sources[0].term
