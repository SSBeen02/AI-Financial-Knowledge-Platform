import pytest

from chatbot.concepts import load_stage_catalog
from chatbot.concept_synonyms import automatic_synonym_report, build_auto_synonyms, concept_terms, explicit_matches, other_name_candidates, term_mentioned
from chatbot.relevance import detect_concept, mentioned_concepts
from chatbot.retrieval import CachedConcept, RetrievedDoc, RetrievalResult
from chatbot.service import _message_notice
from tests.conftest import STAGES_PATH


class Cache:
    def __init__(self, concept):
        self.concept = concept

    def get(self, concept_id):
        return self.concept if concept_id == self.concept.concept_id else None

    def values(self):
        return (self.concept,)


def test_etf_maps_to_regular_concept_even_when_extra_hit_ranks_first():
    regular = next(ref for ref in load_stage_catalog(STAGES_PATH).stages["stage2"].concepts if ref.concept_id == "sisa_1410")
    cached = CachedConcept("sisa_1410", "상장지수펀드", (), "설명: 지수 펀드", None)
    extra = RetrievedDoc("extra_etf", "ETF", 0.8, "sisa_terms", "시사경제용어사전", "설명", None, ("extra",))
    retrieval = RetrievalResult([extra], [extra], "high", 0.8)
    assert detect_concept(question="ETF가 뭐야?", candidates=[regular], cache=Cache(cached), retrieval=retrieval, band_high=0.5) == regular
    assert [item.concept_id for item in mentioned_concepts("ETF와 주식의 차이", [cached], exclude_concept_id="other")] == ["sisa_1410"]


@pytest.mark.parametrize(
    ("stage", "concept_id", "question", "extra_term"),
    [
        ("stage3", "sisa_566", "GDP가 뭐야?", "GDP"),
        ("stage4", "sisa_2082", "M&A가 뭐야?", "M&A"),
        ("stage3", "sisa_1514", "CPI 알려줘", "CPI"),
    ],
)
def test_automatic_alias_prefers_stage_concept_over_extra(stage, concept_id, question, extra_term):
    catalog = load_stage_catalog(STAGES_PATH)
    regular = next(ref for ref in catalog.stages[stage].concepts if ref.concept_id == concept_id)
    cached = CachedConcept(concept_id, regular.term, (), "설명", None)
    extra = RetrievedDoc("extra_hit", extra_term, 0.8, "sisa_terms", "시사경제용어사전", "설명", None, ("extra",))
    retrieval = RetrievalResult([extra], [extra], "high", 0.8)
    assert detect_concept(question=question, candidates=[regular], cache=Cache(cached), retrieval=retrieval, band_high=0.5) == regular

    class Status:
        def get_current_stage(self, user_id):
            return stage

        def get_statuses(self, user_id, stage_id):
            return {}

    assert _message_notice(catalog=catalog, status_service=Status(), cache=Cache(cached),
                           user_id="user", question=question, retrieval=retrieval, chat_tone="hao") is None


def test_english_aliases_require_word_boundaries():
    assert not term_mentioned("models에 대해 알려줘", "ELS")
    assert not term_mentioned("XGDP2에 대해 알려줘", "GDP")
    assert term_mentioned("GDP가 뭐야?", "GDP")
    assert term_mentioned("Exchange Traded Fund가 뭐야?", "Exchange Traded Fund")
    assert term_mentioned("사회 보장 제도가 궁금해", "사회보장제도")


@pytest.mark.parametrize("question,term", [
    ("GDP갭이 뭐야?", "GDP"),
    ("ETF형 상품", "ETF"),
    ("CPI상승률", "CPI"),
    ("GDP가치", "GDP"),
])
def test_english_alias_rejects_attached_korean_noun(question, term):
    assert not term_mentioned(question, term)


@pytest.mark.parametrize("question,term", [
    ("GDP가 뭐야?", "GDP"),
    ("gdp가 뭐야?", "GDP"),
    ("GDP랑 GNP 차이", "GDP"),
    ("ETF가 뭐야?", "ETF"),
    ("ETF랑 ETN 차이가 뭐야?", "ETF"),
    ("inflation이 뭐야?", "Inflation"),
])
def test_english_alias_accepts_particle_and_casefold(question, term):
    assert term_mentioned(question, term)


def test_longer_retrieved_term_suppresses_contained_regular_alias():
    for question, stage, concept_id, regular_term, long_term in (
        ("GDP갭이 뭐야?", "stage3", "sisa_566", "국내총생산/국민총생산", "GDP갭"),
        ("레버리지 ETF가 뭐야?", "stage2", "sisa_1410", "상장지수펀드", "레버리지 ETF"),
    ):
        catalog = load_stage_catalog(STAGES_PATH)
        ref = next(ref for ref in catalog.stages[stage].concepts if ref.concept_id == concept_id)
        cached = CachedConcept(concept_id, regular_term, (), "설명", None)
        extra = RetrievedDoc("extra_long", long_term, 0.8, "sisa_terms", "시사경제용어사전", "설명", None, ("extra",))
        retrieval = RetrievalResult([extra], [extra], "high", 0.8)
        assert detect_concept(question=question, candidates=[ref], cache=Cache(cached), retrieval=retrieval, band_high=0.5) is None
        matches = explicit_matches(question, [(concept_id, "ETF" if "ETF" in question else "GDP"), ("extra_long", long_term)])
        assert matches == [("extra_long", long_term)]

        class Status:
            def get_current_stage(self, user_id):
                return stage

            def get_statuses(self, user_id, stage_id):
                return {}

        notice = _message_notice(catalog=catalog, status_service=Status(), cache=Cache(cached),
                                 user_id="user", question=question, retrieval=retrieval, chat_tone="hao")
        assert long_term in notice
        assert "정규 과정에는 없지만" in notice


def test_korean_other_names_are_not_automatically_registered():
    aliases, rejected = automatic_synonym_report()
    assert "개인파산" not in aliases.get("sisa_1510", ())
    assert ("sisa_1510", "소비자 파산", "개인파산") in rejected["korean"]
    assert "Securities" not in aliases.get("sisa_1992", ())
    assert ("sisa_1992", "유가증권", "Securities") in rejected["single_english_word"]


def test_duplicate_candidate_between_concepts_is_reported_not_registered():
    data = {"stages": [{"concepts": [
        {"concept_id": "one", "term": "첫 개념", "term_full": "첫 개념(GDP)"},
        {"concept_id": "two", "term": "둘째 개념", "term_full": "둘째 개념(GDP)"},
    ]}]}
    aliases, rejected = build_auto_synonyms(data)
    assert "GDP" not in aliases.get("one", ())
    assert "GDP" not in aliases.get("two", ())
    assert len(rejected["duplicate"]) == 2


def test_candidate_split_and_manual_priority():
    assert other_name_candidates("국내총생산(GDP)/국민총생산(GNP)") == ("GDP", "GNP", "국내총생산", "국민총생산")
    assert other_name_candidates("인수합병(Merger and Acquisition; M&A)") == ("Merger and Acquisition", "M&A")
    assert concept_terms("sisa_1410", "상장지수펀드")[:3] == ("상장지수펀드", "ETF", "Exchange Traded Fund")


@pytest.mark.parametrize(
    ("stage", "concept_id", "question"),
    [
        ("stage3", "sisa_566", "국내총생산이 뭐야?"),
        ("stage3", "sisa_566", "국민총생산 알려줘"),
        ("stage1", "sisa_1281", "분업이 뭐야?"),
        ("stage4", "sisa_2794", "평가절하가 뭐야?"),
        ("stage3", "sisa_1514", "생활물가지수는?"),
        ("stage5", "sisa_211", "ROI가 뭐야?"),
    ],
)
def test_split_canonical_term_parts_detect_regular_concept(stage, concept_id, question):
    ref = next(ref for ref in load_stage_catalog(STAGES_PATH).stages[stage].concepts if ref.concept_id == concept_id)
    cached = CachedConcept(concept_id, ref.term, (), "설명", None)
    retrieval = RetrievalResult([], [], "mid", 0.49)
    assert detect_concept(question=question, candidates=[ref], cache=Cache(cached), retrieval=retrieval, band_high=0.5) == ref


@pytest.mark.parametrize(
    ("stage", "concept_id", "question"),
    [
        ("stage3", "sisa_2091", "inflation이 뭐야?"),
        ("stage3", "sisa_2091", "INFLATION"),
        ("stage4", "sisa_2567", "담합이 뭐야?"),
        ("stage4", "sisa_182", "경제협력개발기구가 뭐야?"),
    ],
)
def test_requested_manual_aliases_detect_regular_concept(stage, concept_id, question):
    ref = next(ref for ref in load_stage_catalog(STAGES_PATH).stages[stage].concepts if ref.concept_id == concept_id)
    cached = CachedConcept(concept_id, ref.term, (), "설명", None)
    assert detect_concept(question=question, candidates=[ref], cache=Cache(cached),
                          retrieval=RetrievalResult([], [], "mid", 0.49), band_high=0.5) == ref


def test_unapproved_candidates_stay_unregistered():
    for concept_id, term, excluded in (
        ("sisa_234", "Short Sale", "공매"),
        ("sisa_1992", "유가증권", "Securities"),
        ("sisa_1126", "밀레니얼 세대", "Millenials"),
        ("sisa_177", "Net Present Value", "순현재가치"),
        ("sisa_842", "니트족", "Not in Education"),
    ):
        assert excluded not in concept_terms(concept_id, term)
    ref = next(ref for ref in load_stage_catalog(STAGES_PATH).stages["stage2"].concepts if ref.concept_id == "sisa_234")
    cached = CachedConcept(ref.concept_id, ref.term, (), "설명", None)
    assert detect_concept(question="공매가 뭐야?", candidates=[ref], cache=Cache(cached),
                          retrieval=RetrievalResult([], [], "mid", 0.49), band_high=0.5) is None


def test_duplicate_canonical_term_part_is_not_registered():
    data = {"stages": [{"concepts": [
        {"concept_id": "one", "term": "가치/가격", "term_full": "가치/가격"},
        {"concept_id": "two", "term": "가격·비용", "term_full": "가격·비용"},
    ]}]}
    aliases, rejected = build_auto_synonyms(data)
    assert "가격" not in aliases.get("one", ())
    assert "가격" not in aliases.get("two", ())
    assert len([row for row in rejected["duplicate"] if row[2] == "가격"]) == 2


def test_one_character_canonical_term_part_is_not_registered():
    data = {"stages": [{"concepts": [
        {"concept_id": "one", "term": "가/가격", "term_full": "가/가격"},
    ]}]}
    aliases, _ = build_auto_synonyms(data)
    assert aliases["one"] == ("가격",)


def test_specialization_and_division_both_detect_regular_concept():
    ref = next(ref for ref in load_stage_catalog(STAGES_PATH).stages["stage1"].concepts if ref.concept_id == "sisa_1281")
    cached = CachedConcept(ref.concept_id, ref.term, ("분업", "특화"), "설명", None)
    assert "특화" in concept_terms(ref.concept_id, ref.term, cached.aliases)
    high_hit = RetrievedDoc(ref.concept_id, ref.term, 0.8, "sisa_terms", "시사경제용어사전", "설명", None, ("stage1",))
    high = RetrievalResult([high_hit], [high_hit], "high", 0.8)
    assert detect_concept(question="특화된 서비스가 뭐야?", candidates=[ref], cache=Cache(cached), retrieval=high, band_high=0.5) == ref
    assert detect_concept(question="분업이 뭐야?", candidates=[ref], cache=Cache(cached), retrieval=high, band_high=0.5) == ref
