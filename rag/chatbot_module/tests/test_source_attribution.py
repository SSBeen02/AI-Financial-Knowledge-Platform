"""검색 문서와 답변 첫 정의 문장의 출처 구분."""

import asyncio
import json
from types import SimpleNamespace
from dataclasses import replace
from time import perf_counter

import pytest
from sqlalchemy import inspect

from chatbot.learning_management import DatabaseSchemaNotReadyError
from chatbot.concepts import ConceptRef, StageCatalog, StageRef
from chatbot.prompts import Prompt
from chatbot.retrieval import CachedConcept, RetrievalResult, _retrieved
from chatbot.schemas import MessageIn
from chatbot.service import MessagePlan, PreparedMessage, _definition_term_matches, _display_sources, _ensure_answer_suffixes, _first_definition_sources, _notice_from_answer_definition, _persist_prepared_message, get_message_history, stream_message_events
from chatbot.store import SqlChatStore
from tests.conftest import make_settings
from chatbot.tone import free_question_notice


def _doc(concept_id: str, term: str, aliases: tuple[str, ...] = ()):
    point = SimpleNamespace(
        payload={"concept_id": concept_id, "term": term, "aliases": list(aliases), "text": "설명"},
        score=0.7,
    )
    return _retrieved(point, "sisa_terms", "시사경제용어사전")


def _result(*docs):
    return RetrievalResult(sources=list(docs), concept_hits=list(docs), band="high", top_score=0.7)


def test_first_definition_sources_shared_by_citation_and_notice() -> None:
    matching = _doc("extra", "인구 고령화")
    unrelated = _doc("other", "물가 상승")
    sentence, matches = _first_definition_sources(
        "우리 사회가 늙어가는 현상은 인구 고령화라고 부르오.\n\n참고한 자료: 물가 상승",
        [matching, unrelated],
    )
    assert sentence == "우리 사회가 늙어가는 현상은 인구 고령화라고 부르오."
    assert matches == [matching]
    cited = _ensure_answer_suffixes(sentence, _result(matching, unrelated), "dictionary_plus")
    assert "핵심 정의 출처:" in cited
    assert "(인구 고령화)" in cited


def test_longer_defined_term_excludes_contained_short_alias_source() -> None:
    long = _doc("extra_long", "레버리지 ETF")
    short = _doc("regular", "ETF")
    sentence, matches = _first_definition_sources("레버리지 ETF는 별도 상품이오.", [short, long])
    assert sentence.startswith("레버리지 ETF는")
    assert matches == [long]
    answer = _ensure_answer_suffixes(sentence, _result(short, long), "dictionary_plus")
    assert "(레버리지 ETF)" in answer
    assert "(ETF)" not in answer


def test_contrastive_wag_the_dog_is_not_definition_or_extra_notice() -> None:
    extra = replace(_doc("extra_wag", "Wag the Dog"), stages=("extra",))
    prepared = _prepared(_result(extra))
    body = (
        "고양이가 꼬리를 흔드는 까닭은 경제 용어인 wag the dog(개의 꼬리가 몸통을 흔든다는 뜻)과는 "
        "전혀 다른, 고양이의 몸과 마음 상태를 드러내는 신호이기 때문이오."
    )
    answer = _ensure_answer_suffixes(body, prepared.retrieval, "dictionary_plus")
    assert not _definition_term_matches(body, "Wag the Dog", ())
    assert "핵심 정의 출처:" not in answer
    assert _notice_from_answer_definition(prepared, answer, _Status()) == (free_question_notice("hao"), None)


@pytest.mark.parametrize("sentence", [
    "인구 고령화가 아니라 다른 현상이오.",
    "인구 고령화와 달리 다른 현상이오.",
    "인구 고령화와는 상관없는 이야기요.",
    "인구 고령화과는 전혀 다른 현상이오.",
])
def test_contrastive_or_negative_term_is_not_definition(sentence: str) -> None:
    assert not _definition_term_matches(sentence, "인구 고령화", ())


@pytest.mark.parametrize("sentence,term,aliases", [
    ("ETF는 지수를 따르는 펀드이오.", "ETF", ()),
    ("니트족(NEET)은 교육이나 고용 밖에 있는 청년을 뜻하오.", "니트족", ("NEET",)),
    ("국내총생산(GDP)은 한 나라의 생산 규모를 뜻하오.", "국내총생산/국민총생산", ()),
    ("우리 사회가 늙어가는 현상은 인구 고령화라고 부르오.", "인구 고령화", ()),
    ("인구 고령화라는 것은 인구 구조의 변화를 뜻하오.", "인구 고령화", ()),
])
def test_definition_target_patterns_are_cited(sentence: str, term: str, aliases: tuple[str, ...]) -> None:
    assert _definition_term_matches(sentence, term, aliases)


def _prepared(result, *, tone="hao", notice=None, concept=None):
    refs = (concept,) if concept is not None else ()
    catalog = StageCatalog(
        stages={"stage1": StageRef("stage1", "기초", refs)},
        by_concept={concept.concept_id: refs} if concept is not None else {},
    )
    cache = SimpleNamespace(
        values=lambda: (CachedConcept(concept.concept_id, concept.term, (), "설명", None),) if concept else (),
        get=lambda concept_id: CachedConcept(concept.concept_id, concept.term, (), "설명", None) if concept and concept_id == concept.concept_id else None,
    )
    return PreparedMessage(
        user_id="user", request=MessageIn(message="우리 사회가 늙어가는 걸 뭐라고 해?"),
        plan=MessagePlan(None, None, None, None), retrieval=result, current_concept=None,
        is_related=False, notice=notice or free_question_notice(tone), suggested_concept=None,
        prompt=Prompt("", ""), started_at=perf_counter(), display_source_min_score=0.6,
        chat_tone=tone, answer_knowledge_mode="dictionary_plus", catalog=catalog, cache=cache,
    )


class _Status:
    def __init__(self, status="not_started"):
        self.status = status

    def get_current_stage(self, user_id):
        return "stage1"

    def get_statuses(self, user_id, stage_id):
        return {"regular": self.status}


def test_answer_defined_extra_term_replaces_generic_free_notice() -> None:
    extra = replace(_doc("extra", "인구 고령화"), stages=("extra",))
    prepared = _prepared(_result(extra))
    answer = _ensure_answer_suffixes("우리 사회가 늙어가는 현상은 인구 고령화라고 부르오.", prepared.retrieval, "dictionary_plus")
    assert "핵심 정의 출처:" in answer
    assert _notice_from_answer_definition(prepared, answer, _Status()) == (
        "인구 고령화는 학당의 정규 과정에는 없지만, 알아두면 쓸모 있는 경제 상식이오! 다만 성장과 퀴즈에는 반영되지 않소.", None
    )


def test_answer_defined_excluded_term_uses_term_free_notice() -> None:
    excluded = replace(_doc("excluded", "인구 고령화"), stages=("excluded",))
    prepared = _prepared(_result(excluded), tone="modern")
    notice, suggested = _notice_from_answer_definition(
        prepared, "우리 사회가 늙어가는 현상은 인구 고령화라고 불러요.", _Status()
    )
    assert notice == "인구 고령화에 대해 물어본 것은 자유 질문이라 학습과 성장, 퀴즈에는 반영되지 않아요."
    assert suggested is None


def test_answer_defined_regular_term_suggests_or_reports_passed() -> None:
    regular = replace(_doc("regular", "인구 고령화"), stages=("stage1",))
    ref = ConceptRef("regular", "인구 고령화", "인구 고령화", "경제", 1, "stage1", "기초")
    prepared = _prepared(_result(regular), concept=ref)
    answer = "우리 사회가 늙어가는 현상은 인구 고령화라고 부르오."
    notice, suggested = _notice_from_answer_definition(prepared, answer, _Status())
    assert "이번 스테이지에서 배우는 개념" in notice
    assert suggested.concept_id == "regular"
    assert "이미 통과한 개념" in _notice_from_answer_definition(prepared, answer, _Status("passed"))[0]


def test_answer_defined_other_stage_term_uses_other_stage_notice() -> None:
    regular = replace(_doc("regular", "인구 고령화"), stages=("stage2",))
    ref = ConceptRef("regular", "인구 고령화", "인구 고령화", "경제", 1, "stage2", "심화")
    prepared = _prepared(_result(regular), concept=ref)
    catalog = StageCatalog(
        stages={"stage1": StageRef("stage1", "기초", ()), "stage2": StageRef("stage2", "심화", (ref,))},
        by_concept={"regular": (ref,)},
    )
    prepared = replace(prepared, catalog=catalog)
    notice, suggested = _notice_from_answer_definition(
        prepared, "이 현상은 인구 고령화라고 부르오.", _Status()
    )
    assert "심화에서 배우는 것" in notice
    assert suggested is None


def test_answer_defined_etf_alias_prefers_regular_concept() -> None:
    extra = replace(_doc("extra_etf", "ETF"), stages=("extra",))
    ref = ConceptRef("sisa_1410", "상장지수펀드", "상장지수펀드", "투자", 1, "stage1", "기초")
    prepared = _prepared(_result(extra), concept=ref)
    notice, suggested = _notice_from_answer_definition(prepared, "이 상품은 ETF라고 부르오.", _Status())
    assert "이번 스테이지에서 배우는 개념" in notice
    assert suggested.concept_id == "sisa_1410"


def test_definition_notice_failure_keeps_original_free_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    import chatbot.service as service

    prepared = _prepared(_result(replace(_doc("extra", "인구 고령화"), stages=("extra",))))
    monkeypatch.setattr(service, "_first_definition_sources", lambda *_args: (_ for _ in ()).throw(RuntimeError("test")))
    assert _notice_from_answer_definition(prepared, "인구 고령화라고 부르오.", _Status()) == (
        free_question_notice("hao"), None
    )


def test_stream_done_contains_answer_defined_notice_and_suggestion(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    regular = replace(_doc("regular", "인구 고령화"), stages=("stage1",))
    ref = ConceptRef("regular", "인구 고령화", "인구 고령화", "경제", 1, "stage1", "기초")
    prepared = _prepared(_result(regular), concept=ref)
    answer = "우리 사회가 늙어가는 현상은 인구 고령화라고 부르오."

    settings = make_settings(tmp_path / "stream.db", simulate_quiz_status=False)
    store = SqlChatStore(settings)

    async def connected():
        return False

    async def immediate_thread_call(func, *args):
        return func(*args)

    monkeypatch.setattr(asyncio, "to_thread", immediate_thread_call)

    generator = stream_message_events(
        prepared=prepared, status_service=_Status(), store=store,
        llm=SimpleNamespace(stream=lambda _prompt: iter([answer])),
        is_disconnected=connected, request_id="request-1",
    )
    events = []
    while True:
        pending = generator.__anext__()
        try:
            while True:
                pending.send(None)
        except StopIteration as emitted:
            events.append(emitted.value)
        except StopAsyncIteration:
            break
    done = json.loads(next(event.split("data: ", 1)[1] for event in events if event.startswith("event: done")))
    assert done["notice"] == "인구 고령화는 이번 스테이지에서 배우는 개념이오. 학습으로 남기려면 아래 버튼을 눌러 시작해 보시오."
    assert done["suggested_concept"] == {"concept_id": "regular", "term": "인구 고령화"}
    assert get_message_history(store, settings, "user", limit=10)[-1].notice == done["notice"]
    store.close()


def test_final_free_notice_is_saved_and_restored(tmp_path) -> None:
    store = SqlChatStore(make_settings(tmp_path / "chat.db", simulate_quiz_status=False))
    try:
        prepared = _prepared(_result(_doc("other", "물가 상승")))
        response = _persist_prepared_message(
            prepared=prepared, answer="우리 사회가 변하고 있소.", status_service=_Status(), store=store,
        )
        history = get_message_history(store, make_settings(tmp_path / "chat.db", simulate_quiz_status=False), "user", limit=10)
        assert response.notice == free_question_notice("hao")
        assert [item.notice for item in history] == [None, response.notice]
        assert [item.session_id for item in history] == [None, None]
    finally:
        store.close()


def test_corrected_extra_notice_is_saved_and_restored(tmp_path) -> None:
    store = SqlChatStore(make_settings(tmp_path / "chat.db", simulate_quiz_status=False))
    try:
        extra = replace(_doc("extra", "인구 고령화"), stages=("extra",))
        response = _persist_prepared_message(
            prepared=_prepared(_result(extra)),
            answer="우리 사회가 늙어가는 현상은 인구 고령화라고 부르오.",
            status_service=_Status(), store=store,
        )
        history = get_message_history(store, make_settings(tmp_path / "chat.db", simulate_quiz_status=False), "user", limit=10)
        assert "정규 과정에는 없지만" in response.notice
        assert history[-1].notice == response.notice
    finally:
        store.close()


def test_session_notice_is_null_and_quiz_turns_ignore_free_messages(tmp_path) -> None:
    store = SqlChatStore(make_settings(tmp_path / "chat.db", simulate_quiz_status=False))
    try:
        store.save_message_pair(user_id="user", session_id=None, question="자유 질문", answer="자유 답변", is_related=False,
                                band="high", top_score=0.7, sources=[], latency_ms=1, notice="자유 질문 안내")
        session = store.create_session(user_id="user", stage="stage1", concept_id="regular", term="정규 개념", attempt=1, start_type="keyword")
        store.save_message_pair(user_id="user", session_id=session.session_id, question="학습 질문", answer="학습 답변", is_related=True,
                                band="high", top_score=0.7, sources=[], latency_ms=1)
        history = get_message_history(store, make_settings(tmp_path / "chat.db", simulate_quiz_status=False), "user", limit=10)
        assert [item.notice for item in history] == [None, "자유 질문 안내", None, None]
        assert [item.content for item in store.get_session_messages("user", session.session_id)] == ["학습 질문", "학습 답변"]
    finally:
        store.close()


def test_existing_sqlite_adds_notice_column_without_losing_messages(tmp_path) -> None:
    settings = make_settings(tmp_path / "existing.db", simulate_quiz_status=False)
    store = SqlChatStore(settings)
    store.save_message_pair(user_id="user", session_id=None, question="옛 질문", answer="옛 답변", is_related=False,
                            band="high", top_score=0.7, sources=[], latency_ms=1)
    with store._engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE learning_messages DROP COLUMN notice")
    store.close()
    with pytest.raises(DatabaseSchemaNotReadyError, match="006_add_learning_message_notice"):
        SqlChatStore(settings.model_copy(update={"db_auto_create": False}))
    upgraded = SqlChatStore(settings)
    try:
        assert "notice" in {column["name"] for column in inspect(upgraded._engine).get_columns("learning_messages")}
        assert [item.content for item in upgraded.get_recent_messages("user", limit=10)] == ["옛 질문", "옛 답변"]
        assert [item.notice for item in upgraded.get_recent_messages("user", limit=10)] == [None, None]
    finally:
        upgraded.close()


def test_answer_notice_only_changes_for_matched_generic_free_question() -> None:
    extra = replace(_doc("extra", "인구 고령화"), stages=("extra",))
    prepared = _prepared(_result(extra))
    answer = "우리 사회는 점점 늙어가오."
    assert _notice_from_answer_definition(prepared, answer, _Status())[0] == free_question_notice("hao")
    protected = replace(prepared, notice="이미 다른 안내", suggested_concept=None)
    assert _notice_from_answer_definition(protected, "인구 고령화라고 부르오.", _Status())[0] == "이미 다른 안내"
    low = replace(prepared, retrieval=replace(prepared.retrieval, band="low"))
    assert _notice_from_answer_definition(low, "인구 고령화라고 부르오.", _Status())[0] == free_question_notice("hao")


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
