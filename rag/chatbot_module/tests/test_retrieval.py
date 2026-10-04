from __future__ import annotations

from chatbot.config import Settings
from chatbot.retrieval import (
    ConceptCache,
    ConceptCacheError,
    RetrievalError,
    Retriever,
    concept_point_id,
    judge_band,
    to_source_out,
)

SISA = {
    "mode": "dense",
    "k": 5,
    "slots": 3,
    "label": "시사경제용어사전",
    "concept_source": True,
}
TEXTBOOK = {
    "mode": "dense",
    "k": 5,
    "slots": 2,
    "label": "교재",
    "concept_source": False,
}


def _settings() -> Settings:
    return Settings(_env_file=None, llm_model="gpt-test", band_high=0.50, band_low=0.45)


class Point:
    def __init__(self, doc_id: str, score: float, payload: dict | None = None, point_id: str | None = None):
        self.id = point_id or concept_point_id(doc_id)
        self.score = score
        self.payload = {"doc_id": doc_id, "term": doc_id, "text": f"{doc_id} 설명"} if payload is None else payload


def _search_factory(catalog: dict[str, list[Point]]):
    calls: list[tuple[str, str, int]] = []

    def search(client, query, dense, sparse, mode="hybrid", k=5, stage=None, collection="sisa_terms", prefetch_k=30):
        calls.append((collection, mode, k))
        return catalog.get(collection, [])[:k]

    return search, calls


def test_band_boundaries() -> None:
    assert judge_band(0.50, high=0.50, low=0.45) == "high"
    assert judge_band(0.90, high=0.50, low=0.45) == "high"
    assert judge_band(0.45, high=0.50, low=0.45) == "mid"
    assert judge_band(0.499, high=0.50, low=0.45) == "mid"
    assert judge_band(0.449, high=0.50, low=0.45) == "low"


def test_single_source_keeps_slot_count_and_dense_band() -> None:
    points = [Point(f"sisa_{index}", score) for index, score in enumerate((0.71, 0.66, 0.61, 0.40, 0.20), start=1)]
    search, calls = _search_factory({"sisa_terms": points})
    result = Retriever(object(), object(), _settings(), profiles={"sisa_terms": SISA}, search_fn=search).search("기회비용")
    assert calls == [("sisa_terms", "dense", 5)]
    assert [item.doc_id for item in result.sources] == ["sisa_1", "sisa_2", "sisa_3"]
    assert result.top_score == 0.71
    assert result.band == "high"
    dumped = to_source_out(result.sources[0]).model_dump()
    assert dumped["label"] == "시사경제용어사전"
    assert "images" not in dumped


def test_images_are_kept_only_when_payload_has_them() -> None:
    with_images = Point(
        "sisa_1",
        0.8,
        {"doc_id": "sisa_1", "term": "용어", "text": "본문", "images": ["https://example.com/a.png"]},
    )
    without = Point("sisa_2", 0.6, {"doc_id": "sisa_2", "term": "다른용어", "text": "본문"})
    search, _calls = _search_factory({"sisa_terms": [with_images, without]})
    profile = {**SISA, "slots": 2, "k": 2}
    result = Retriever(object(), object(), _settings(), profiles={"sisa_terms": profile}, search_fn=search).search("질문")
    assert to_source_out(result.sources[0]).model_dump()["images"] == ["https://example.com/a.png"]
    assert "images" not in to_source_out(result.sources[1]).model_dump()


def test_profiles_merge_by_slots_and_band_ignores_other_sources() -> None:
    search, calls = _search_factory(
        {
            "sisa_terms": [Point("sisa_mid", 0.46), Point("sisa_next", 0.10)],
            "textbook": [Point("book_high", 0.99), Point("book_next", 0.98), Point("book_drop", 0.97)],
        }
    )
    profiles = {"sisa_terms": {**SISA, "slots": 1, "k": 2}, "textbook": {**TEXTBOOK, "slots": 2, "k": 3}}
    result = Retriever(object(), object(), _settings(), profiles=profiles, search_fn=search).search("질문")
    assert [item.doc_id for item in result.sources] == ["sisa_mid", "book_high", "book_next"]
    assert [item.label for item in result.sources] == ["시사경제용어사전", "교재", "교재"]
    assert result.top_score == 0.46
    assert result.band == "mid"
    assert calls == [("sisa_terms", "dense", 2), ("textbook", "dense", 3)]


def test_empty_concept_source_is_low_band() -> None:
    search, _calls = _search_factory({"sisa_terms": []})
    result = Retriever(object(), object(), _settings(), profiles={"sisa_terms": SISA}, search_fn=search).search("오늘 날씨")
    assert result.sources == []
    assert result.concept_hits == []
    assert result.top_score == 0.0
    assert result.band == "low"


def test_low_band_hides_sources_but_keeps_concept_hits() -> None:
    search, _calls = _search_factory({"sisa_terms": [Point("sisa_low", 0.20)]})
    result = Retriever(
        object(), object(), _settings(), profiles={"sisa_terms": SISA}, search_fn=search
    ).search("질문")
    assert result.band == "low"
    assert result.top_score == 0.20
    assert result.sources == []
    assert [item.doc_id for item in result.concept_hits] == ["sisa_low"]


def test_non_dense_profile_without_sparse_encoder_is_rejected() -> None:
    profile = {**SISA, "mode": "hybrid"}
    retriever = Retriever(object(), object(), _settings(), profiles={"sisa_terms": profile}, search_fn=lambda **kwargs: [])
    try:
        retriever.search("질문")
    except RetrievalError as exc:
        assert "희소 인코더" in exc.detail
    else:
        raise AssertionError("hybrid 프로필은 희소 인코더 없이 검색되면 안 됩니다.")


class Store:
    def __init__(self, points: list[Point], scroll_points: list[Point] | None = None):
        self.points = points
        self.scroll_points = scroll_points or []
        self.retrieve_ids: list[list[str]] = []

    def retrieve(self, collection_name: str, ids: list[str], **kwargs: object) -> list[Point]:
        self.retrieve_ids.append(list(ids))
        wanted = set(ids)
        return [point for point in self.points if point.id in wanted]

    def scroll(self, collection_name: str, **kwargs: object) -> tuple[list[Point], None]:
        return self.scroll_points, None


def test_concept_cache_reads_payload_by_point_id() -> None:
    point = Point(
        "sisa_745",
        0.0,
        {"doc_id": "sisa_745", "term": "기회비용", "aliases": ["Opportunity Cost"], "text": "설명: 포기한 가치"},
    )
    cache = ConceptCache(Store([point]), "sisa_terms", ["sisa_745"])
    loaded = cache.get("sisa_745")
    assert loaded is not None
    assert loaded.term == "기회비용"
    assert loaded.aliases == ("Opportunity Cost",)
    assert loaded.text == "설명: 포기한 가치"
    assert loaded.images is None
    assert cache.get("sisa_missing") is None
    assert [item.doc_id for item in cache.values()] == ["sisa_745"]


def test_concept_cache_falls_back_to_doc_id_filter() -> None:
    point = Point("sisa_745", 0.0, {"doc_id": "sisa_745", "term": "기회비용", "aliases": [], "text": "본문"})
    cache = ConceptCache(Store([], scroll_points=[point]), "sisa_terms", ["sisa_745"])
    loaded = cache.get("sisa_745")
    assert loaded is not None
    assert loaded.term == "기회비용"


def test_concept_cache_reports_missing_documents() -> None:
    try:
        ConceptCache(Store([]), "sisa_terms", ["sisa_missing"])
    except ConceptCacheError as exc:
        assert "sisa_missing" in exc.detail
    else:
        raise AssertionError("없는 개념 문서는 캐시 적재에 실패해야 합니다.")
