"""검색 문서와 답변 첫 정의 문장의 출처 구분."""

from types import SimpleNamespace

from chatbot.retrieval import CachedConcept, RetrievalResult, _retrieved
from chatbot.service import _definition_term_matches, _display_sources, _ensure_answer_suffixes


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


def test_fss_book_source_is_visible_and_cited_at_rrf_score() -> None:
    point = SimpleNamespace(id="chunk-1", payload={"chunk_id": "chunk-1", "title": "신용관리", "text": "설명"}, score=0.5)
    book = _retrieved(point, "fss_practical_finance_4e_3p_kure_v1", "대학생을 위한 실용금융(제4판)_금융감독원_2024")
    result = _result(book)
    assert _display_sources(result, current_concept_id=None, minimum_score=0.6) == [book]
    answer = _ensure_answer_suffixes("신용관리는 신용을 꾸준히 관리하는 일이오.", result, "dictionary_plus")
    assert "핵심 정의 출처: 대학생을 위한 실용금융(제4판)_금융감독원_2024 (신용관리)" in answer
    other = _ensure_answer_suffixes("예산은 수입과 지출을 계획하는 일이오.", result, "dictionary_plus")
    assert "참고한 자료: 대학생을 위한 실용금융(제4판)_금융감독원_2024" in other
    assert "※ 핵심 정의는 일반 경제 지식을 바탕으로 설명했소" in other


def test_mixed_sources_footer_lists_labels_once() -> None:
    book = _retrieved(
        SimpleNamespace(id="chunk-1", payload={"section": "은행의 기원", "content_markdown": "본문"}, score=0.5),
        "fss_practical_finance_4e_3p_kure_v1",
        "대학생을 위한 실용금융(제4판)_금융감독원_2024",
    )
    answer = _ensure_answer_suffixes(
        "은행은 금융기관이오.",
        _result(_doc("sisa_1", "제2금융권"), _doc("sisa_2", "선도은행"), book),
        "dictionary_plus",
    )
    assert answer.count("재정경제부_시사경제용어 정보 (공공데이터포털)") == 1
    assert answer.count("대학생을 위한 실용금융(제4판)_금융감독원_2024") == 1
    assert "참고한 자료:" in answer
    assert "제2금융권" not in answer


def test_bok_dense_source_uses_existing_display_threshold() -> None:
    label = "2026_경제금융용어 800선_한국은행"
    docs = [
        _retrieved(SimpleNamespace(id="bok-1", payload={"term": "SOFR", "content_markdown": "본문"}, score=0.68),
                   "bok_economic_financial_terms_2026_kure_v1_rrf", label),
        _retrieved(SimpleNamespace(id="bok-2", payload={"term": "콜금리", "content_markdown": "본문"}, score=0.55),
                   "bok_economic_financial_terms_2026_kure_v1_rrf", label),
    ]
    assert _display_sources(_result(*docs), current_concept_id=None, minimum_score=0.6) == docs[:1]
    assert _display_sources(
        _result(*docs), current_concept_id=None, minimum_score=0.6,
        answer="콜금리는 금융기관끼리 빌린 돈에 붙는 금리이오.",
    ) == docs
