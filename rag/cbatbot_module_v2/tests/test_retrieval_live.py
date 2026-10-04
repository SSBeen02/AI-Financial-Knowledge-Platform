"""Qdrant와 임베딩 모델이 있을 때만 실행하는 검색 확인."""

from __future__ import annotations

import pytest

from chatbot.config import Settings
from chatbot.deps import get_concept_cache, get_retriever
from chatbot.retrieval import judge_band


def _live_settings() -> Settings | None:
    settings = Settings()
    if not settings.qdrant_url or not settings.qdrant_api_key:
        return None
    return settings


@pytest.mark.integration
def test_live_opportunity_cost_search() -> None:
    settings = _live_settings()
    if settings is None:
        pytest.skip("Qdrant 접속 정보가 없습니다.")
    result = get_retriever().search("기회비용이 뭐야?")
    assert result.sources
    assert len(result.sources) <= 3
    assert result.band == judge_band(result.top_score, high=settings.band_high, low=settings.band_low)
    assert result.top_score == result.sources[0].score
    assert result.sources[0].collection == settings.qdrant_collection
    cache = get_concept_cache()
    cached = cache.get(result.sources[0].concept_id)
    assert cached is not None
    assert cached.concept_id == result.sources[0].concept_id
    assert cached.term == result.sources[0].term
