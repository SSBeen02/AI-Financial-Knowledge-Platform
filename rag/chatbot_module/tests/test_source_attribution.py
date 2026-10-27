"""검색 문서와 답변 첫 정의 문장의 출처 구분."""

from types import SimpleNamespace

from chatbot.retrieval import CachedConcept, RetrievalResult, _retrieved
from chatbot.service import _definition_term_matches, _ensure_answer_suffixes


def _doc(concept_id: str, term: str, aliases: tuple[str, ...] = ()):
    point = SimpleNamespace(
        payload={"concept_id": concept_id, "term": term, "aliases": list(aliases), "text": "설명"},
        score=0.7,
    )
    return _retrieved(point, "sisa_terms", "시사경제용어사전")


def _result(*docs):
    return RetrievalResult(sources=list(docs), concept_hits=list(docs), band="high", top_score=0.7)


def test_q028_and_q020_become_reference_items_without_partial_match() -> None:
    q028 = _ensure_answer_suffixes(
        "물가와 실업이 함께 오르는 상황은 스태그플레이션이라고 하오.",
        _result(_doc("sisa_2091", "인플레이션(Inflation)"), _doc("sisa_1810", "에코플레이션")),
        "dictionary_plus",
    )
    q020 = _ensure_answer_suffixes(
        "CPI는 소비자물가지수라는 뜻이오.",
        _result(_doc("sisa_2466", "차이나플레이션"), _doc("sisa_1430", "생활물가지수(CPI for Living Necessaries)")),
        "dictionary_plus",
        chat_tone="modern",
    )
    assert "참고한 사전 항목: (인플레이션(Inflation), 에코플레이션)" in q028
    assert "핵심 정의는 일반 경제 지식을 바탕으로 설명했소" in q028
    assert "참고한 사전 항목: (차이나플레이션, 생활물가지수(CPI for Living Necessaries))" in q020
    assert "핵심 정의는 일반 경제 지식을 바탕으로 설명했어요" in q020
    assert "핵심 정의 출처:" not in q028 + q020
    assert not _definition_term_matches("소비자물가지수는 지표이오.", "물가지수", ())


def test_only_matching_document_and_payload_alias_are_cited() -> None:
    inflation = _doc("sisa_2091", "인플레이션(Inflation)", ("물가상승",))
    eco = _doc("sisa_1810", "에코플레이션")
    answer = _ensure_answer_suffixes(
        "물가상승은 물가가 전반적으로 오르는 현상이오.",
        _result(inflation, eco),
        "dictionary_plus",
    )
    assert answer.endswith("핵심 정의 출처: 재정경제부_시사경제용어 정보 (공공데이터포털) (인플레이션(Inflation))")
    assert "에코플레이션" not in answer


def test_current_learning_concept_can_support_definition_without_search_hit() -> None:
    current = CachedConcept("sisa_1281", "분업/특화", ("분업",), "설명", None)
    answer = _ensure_answer_suffixes(
        "분업은 일을 나누는 방식이오.", _result(_doc("sisa_2091", "인플레이션")),
        "dictionary_plus", current_concept=current,
    )
    assert "핵심 정의 출처:" in answer
    assert "(분업/특화)" in answer
    assert "인플레이션" not in answer
