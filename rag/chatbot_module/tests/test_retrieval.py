from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from qdrant_client import models

from chatbot.config import Settings
from chatbot.retrieval import (
    ConceptCache,
    ConceptCacheError,
    RetrievalError,
    Retriever,
    concept_point_id,
    judge_band,
    normalize_search_query,
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
    def __init__(self, concept_id: str, score: float, payload: dict | None = None, point_id: str | None = None):
        self.id = point_id or concept_point_id(concept_id)
        self.score = score
        self.payload = {"concept_id": concept_id, "term": concept_id, "text": f"{concept_id} 설명"} if payload is None else payload


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
    assert judge_band(0.49, high=0.50, low=0.49) == "mid"
    assert judge_band(0.489, high=0.50, low=0.49) == "low"


def test_search_joins_only_spaced_single_hangul_run() -> None:
    original = "오늘은 장 수 리 스 크에 대해 알려줘"
    expected = "오늘은 장수리스크에 대해 알려줘"
    terms = ["장수리스크"]
    assert normalize_search_query(original, terms) == expected
    assert normalize_search_query("장 수 리 스 크 에 대 해 알 려 줘 가 가", terms) == "장수리스크 에 대 해 알 려 줘 가 가"
    assert normalize_search_query("예시 하나만 더 들어줘", terms) == "예시 하나만 더 들어줘"
    assert normalize_search_query("그럼 반대 경우는?", terms) == "그럼 반대 경우는?"
    assert normalize_search_query("한 글자만 더 설명해 줘", terms) == "한 글자만 더 설명해 줘"
    assert normalize_search_query("그 때 한 번 더 설명해 줘", terms) == "그 때 한 번 더 설명해 줘"
    assert normalize_search_query("잠이 안 올 때 어떻게 해야 해?", terms) == "잠이 안 올 때 어떻게 해야 해?"

    seen: list[str] = []
    def search(_client, query, _dense, _sparse, **_kwargs):
        seen.append(query)
        return [Point("sisa_2173", 0.2)]

    retriever = Retriever(object(), object(), _settings(), profiles={"sisa_terms": SISA}, search_fn=search)
    retriever.search(normalize_search_query(original, terms))
    assert seen == [expected]
    assert original == "오늘은 장 수 리 스 크에 대해 알려줘"


def test_single_source_keeps_slot_count_and_dense_band() -> None:
    points = [Point(f"sisa_{index}", score) for index, score in enumerate((0.71, 0.66, 0.61, 0.40, 0.20), start=1)]
    search, calls = _search_factory({"sisa_terms": points})
    result = Retriever(object(), object(), _settings(), profiles={"sisa_terms": SISA}, search_fn=search).search("기회비용")
    assert calls == [("sisa_terms", "dense", 5)]
    assert [item.concept_id for item in result.sources] == ["sisa_1", "sisa_2", "sisa_3"]
    assert result.top_score == 0.71
    assert result.band == "high"
    dumped = to_source_out(result.sources[0]).model_dump()
    assert dumped["label"] == "재정경제부_시사경제용어 정보 (공공데이터포털)"
    assert "images" not in dumped


def test_images_are_kept_only_when_payload_has_them() -> None:
    with_images = Point(
        "sisa_1",
        0.8,
        {"concept_id": "sisa_1", "term": "용어", "text": "본문", "images": ["https://example.com/a.png"]},
    )
    without = Point("sisa_2", 0.6, {"concept_id": "sisa_2", "term": "다른용어", "text": "본문"})
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
    assert [item.concept_id for item in result.sources] == ["sisa_mid", "book_high", "book_next"]
    assert [item.label for item in result.sources] == ["시사경제용어사전", "교재", "교재"]
    assert result.top_score == 0.46
    assert result.band == "mid"
    assert calls == [("sisa_terms", "dense", 2), ("textbook", "dense", 3)]


def test_fss_profile_uses_200_candidates_and_keeps_book_source() -> None:
    calls: list[dict] = []

    def search(_client, _query, _dense, sparse, **kwargs):
        calls.append({**kwargs, "sparse": sparse})
        if kwargs["collection"] == "sisa_terms":
            return [Point("sisa_1", 0.7)]
        if kwargs["collection"] != "fss_practical_finance_4e_3p_kure_v1":
            return []
        return [
            Point("book_1", 0.5, {"chunk_id": "book_1", "title": "신용관리", "content": "신용점수 설명"}),
            Point("book_2", 0.333, {"chunk_id": "book_2", "title": "은행의 기원", "content": "은행 설명"}),
        ]

    sparse = object()
    result = Retriever(object(), object(), _settings(), search_fn=search, sparse=sparse).search("신용관리")
    assert calls[0]["mode"] == "dense"
    assert calls[1] == {
        "mode": "hybrid", "k": 5,
        "collection": "fss_practical_finance_4e_3p_kure_v1",
        "prefetch_k": 200, "sparse": sparse,
    }
    assert result.band == "high"
    assert [source.concept_id for source in result.sources] == ["sisa_1", "book_1", "book_2"]
    assert result.sources[1].text == "신용점수 설명"
    assert to_source_out(result.sources[1]).label == "대학생을 위한 실용금융(제4판)_금융감독원_2024"


def test_bok_uses_dense_and_preserves_citation_metadata() -> None:
    from chatbot.config import SEARCH_PROFILES

    search, calls = _search_factory({
        "sisa_terms": [Point("sisa_1", 0.72)],
        "bok_economic_financial_terms_2026_kure_v1_rrf": [Point(
            "bok_1", 0.68,
            {"document_id": "bok_1", "term": "SOFR", "content_markdown": "SOFR 설명",
             "printed_page": 402, "source_url": "https://www.bok.or.kr/example"},
        )],
    })
    profiles = {
        "sisa_terms": SEARCH_PROFILES["sisa_terms"],
        "bok_economic_financial_terms_2026_kure_v1_rrf": SEARCH_PROFILES["bok_economic_financial_terms_2026_kure_v1_rrf"],
    }
    result = Retriever(object(), object(), _settings(), profiles=profiles, search_fn=search).search("SOFR")
    assert calls == [
        ("sisa_terms", "dense", 5),
        ("bok_economic_financial_terms_2026_kure_v1_rrf", "dense", 5),
    ]
    assert result.band == "high" and result.top_score == 0.72
    assert result.sources[1].text == "SOFR 설명"
    source = to_source_out(result.sources[1]).model_dump()
    assert source["term"] == "SOFR"
    assert source["printed_page"] == 402
    assert source["source_url"] == "https://www.bok.or.kr/example"


def test_three_default_sources_keep_their_own_slots() -> None:
    search, calls = _search_factory({
        "sisa_terms": [Point(f"sisa_{n}", 0.7 - n * 0.01) for n in range(4)],
        "fss_practical_finance_4e_3p_kure_v1": [Point(f"fss_{n}", 0.5) for n in range(3)],
        "bok_economic_financial_terms_2026_kure_v1_rrf": [Point(f"bok_{n}", 0.68) for n in range(3)],
    })
    result = Retriever(object(), object(), _settings(), search_fn=search, sparse=object()).search("금융")
    assert [doc.concept_id for doc in result.sources] == [
        "sisa_0", "sisa_1", "sisa_2", "fss_0", "fss_1", "bok_0", "bok_1",
    ]
    assert calls == [
        ("sisa_terms", "dense", 5),
        ("fss_practical_finance_4e_3p_kure_v1", "hybrid", 5),
        ("bok_economic_financial_terms_2026_kure_v1_rrf", "dense", 5),
    ]


def test_fss_malformed_section_uses_chapter_title() -> None:
    from chatbot.retrieval import _retrieved

    point = Point("book_1", 0.5, {
        "section": "어음인수, 상호부금,7 보호예수8 등이 있다. 겸영업무는 다른 업종의 업무 중 은행이 영위",
        "chapter_title": "금융상품, 금융서비스와 금융회사",
        "content_markdown": "은행은 다양한 업무를 맡는다.",
    })
    doc = _retrieved(point, "fss_practical_finance_4e_3p_kure_v1", "교재")
    assert doc.term == "금융상품, 금융서비스와 금융회사"
    point.payload["section"] = "은행은 어떤 종류일까요?"
    assert _retrieved(point, "fss_practical_finance_4e_3p_kure_v1", "교재").term == "금융상품, 금융서비스와 금융회사"


def test_fss_qdrant_query_uses_dense_and_bm25_with_rrf() -> None:
    class Dense:
        def encode(self, texts):
            assert texts == ["신용관리"]
            return np.array([[0.1, 0.2]])

    class Sparse:
        def encode_query(self, query):
            assert query == "신용관리"
            return models.SparseVector(indices=[12], values=[1.0])

    class Client:
        def query_points(self, **kwargs):
            assert kwargs["collection_name"] == "fss_practical_finance_4e_3p_kure_v1"
            assert [(item.using, item.limit) for item in kwargs["prefetch"]] == [("dense", 200), ("bm25", 200)]
            assert kwargs["query"] == models.RrfQuery(rrf=models.Rrf(k=2, weights=[1.0, 1.0]))
            assert kwargs["limit"] == 5
            assert kwargs["with_vectors"] == ["dense"]
            return SimpleNamespace(points=[
                SimpleNamespace(id="chunk-1", score=0.5, vector={"dense": [0.1, 0.2]}, payload={
                    "source_id": "chapter-1", "chunk_index": 1, "section": "1.1 신용",
                    "content_markdown": "신용의 의미", "book_title": "대학생을 위한 실용금융",
                }),
                SimpleNamespace(id="chunk-2", score=0.75, vector={"dense": [0.2, -0.1]}, payload={
                    "section": "무관한 항목", "content_markdown": "다른 내용",
                }),
            ])

    from chatbot.config import SEARCH_PROFILES
    profile = SEARCH_PROFILES["fss_practical_finance_4e_3p_kure_v1"]
    retriever = Retriever(Client(), Dense(), _settings(), sparse=Sparse())
    points = retriever._search_named_sparse("신용관리", "fss_practical_finance_4e_3p_kure_v1", profile)
    assert [point.id for point in points] == ["chunk-1"]
    from chatbot.retrieval import _retrieved
    doc = _retrieved(points[0], "fss_practical_finance_4e_3p_kure_v1", profile["label"])
    assert doc.concept_id == "chunk-1"
    assert doc.term == "1.1 신용"
    assert doc.text == "신용의 의미"


def test_fss_empty_bm25_query_uses_one_rrf_weight() -> None:
    class Dense:
        def encode(self, texts):
            return np.array([[0.1, 0.2]])

    class Sparse:
        def encode_query(self, query):
            return models.SparseVector(indices=[], values=[])

    class Client:
        def query_points(self, **kwargs):
            assert [item.using for item in kwargs["prefetch"]] == ["dense"]
            assert kwargs["query"] == models.RrfQuery(rrf=models.Rrf(k=2, weights=[1.0]))
            return SimpleNamespace(points=[])

    from chatbot.config import SEARCH_PROFILES
    profile = SEARCH_PROFILES["fss_practical_finance_4e_3p_kure_v1"]
    retriever = Retriever(Client(), Dense(), _settings(), sparse=Sparse())
    assert retriever._search_named_sparse("FTA가 뭐야?", "fss_practical_finance_4e_3p_kure_v1", profile) == []


def test_named_sparse_search_rejects_another_collection_model() -> None:
    from chatbot.config import SEARCH_PROFILES

    class Sparse:
        collection = "fss_practical_finance_4e_3p_kure_v1"

    profile = {**SEARCH_PROFILES["bok_economic_financial_terms_2026_kure_v1_rrf"],
               "mode": "hybrid", "sparse_vector": "bm25"}
    retriever = Retriever(object(), object(), _settings(), sparse=Sparse())
    try:
        retriever._search_named_sparse("질문", "bok_economic_financial_terms_2026_kure_v1_rrf", profile)
    except RetrievalError as exc:
        assert "희소 인코더" in exc.detail
    else:
        raise AssertionError("교재 BM25 모델을 한국은행 컬렉션에 재사용하면 안 됩니다.")


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
    assert [item.concept_id for item in result.concept_hits] == ["sisa_low"]


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
        {"concept_id": "sisa_745", "term": "기회비용", "aliases": ["Opportunity Cost"], "text": "설명: 포기한 가치"},
    )
    cache = ConceptCache(Store([point]), "sisa_terms", ["sisa_745"])
    loaded = cache.get("sisa_745")
    assert loaded is not None
    assert loaded.term == "기회비용"
    assert loaded.aliases == ("Opportunity Cost",)
    assert loaded.text == "설명: 포기한 가치"
    assert loaded.images is None
    assert cache.get("sisa_missing") is None
    assert [item.concept_id for item in cache.values()] == ["sisa_745"]


def test_concept_cache_keeps_legacy_qdrant_doc_id_compatibility() -> None:
    point = Point("sisa_745", 0.0, {"doc_id": "sisa_745", "term": "기회비용", "aliases": [], "text": "본문"})
    cache = ConceptCache(Store([], scroll_points=[point]), "sisa_terms", ["sisa_745"])
    loaded = cache.get("sisa_745")
    assert loaded is not None
    assert loaded.term == "기회비용"


def test_retrieved_document_accepts_legacy_qdrant_doc_id() -> None:
    point = Point("sisa_745", 0.72, {"doc_id": "sisa_745", "term": "기회비용", "text": "본문"})
    search, _calls = _search_factory({"sisa_terms": [point]})
    result = Retriever(object(), object(), _settings(), profiles={"sisa_terms": SISA}, search_fn=search).search("기회비용")
    assert result.concept_hits[0].concept_id == "sisa_745"


def test_retrieved_document_keeps_aliases_for_explicit_notice_matching() -> None:
    point = Point(
        "extra_1",
        0.72,
        {
            "concept_id": "extra_1",
            "term": "부가경제용어",
            "aliases": ["경제상식별칭"],
            "stages": ["extra"],
            "text": "설명",
        },
    )
    settings = Settings(_env_file=None, llm_model="gpt-test")
    retriever = Retriever(
        object(),
        object(),
        settings,
        profiles={"sisa_terms": SISA},
        search_fn=lambda *args, **kwargs: [point],
        dense_score_fn=lambda *args, **kwargs: 0.72,
    )

    result = retriever.search("경제상식별칭")

    assert result.concept_hits[0].aliases == ("경제상식별칭",)


def test_concept_cache_reports_missing_documents() -> None:
    try:
        ConceptCache(Store([]), "sisa_terms", ["sisa_missing"])
    except ConceptCacheError as exc:
        assert "sisa_missing" in exc.detail
    else:
        raise AssertionError("없는 개념 문서는 캐시 적재에 실패해야 합니다.")
