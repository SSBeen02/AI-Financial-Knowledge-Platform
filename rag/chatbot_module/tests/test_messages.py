from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbot.answer_format import IncrementalAnswerFormatter
from chatbot.concepts import STATUS_IN_PROGRESS, STATUS_NOT_STARTED, STATUS_PASSED, load_stage_catalog
from chatbot.config import Settings
from chatbot.deps import (
    get_cached_settings,
    get_chat_store,
    get_concept_cache,
    get_concept_status_service,
    get_llm_adapter,
    get_retriever,
    get_quiz_service,
    get_stage_catalog,
)
from chatbot.integrations import SqlConceptStatusService
from chatbot.errors import install_learning_error_handlers
from chatbot.llm import LLMAdapter, LLMError
from chatbot.quiz import DevQuizService, QuizServiceError
from chatbot.prompts import HistoryTurn, Prompt
from chatbot.retrieval import CachedConcept, RetrievedDoc, RetrievalResult
from chatbot.router import router
from chatbot.schemas import MessageIn
from chatbot.service import prepare_message, stream_message_events
from chatbot.store import LearningMessageRow, SqlChatStore
from tests.conftest import STAGES_PATH, force_concept_status, make_settings

USER = "message-user"
HEADERS = {"X-User-Id": USER}
DIVISION = "sisa_1281"
WORKING_POOR = "sisa_1963"
GENTRIFICATION = "sisa_2309"
DEMAND = "sisa_1552"
INFLATION = "sisa_2091"
DEFLATION = "sisa_960"
EIGHTY_EIGHT = "sisa_15"
LONGEVITY = "sisa_2173"
EXTRA_TERM = "extra_1"
EXCLUDED_TERM = "excluded_1"


def _complete_headers(key: str) -> dict[str, str]:
    return {**HEADERS, "Idempotency-Key": key}


def _quiz_result_body(passed: bool, submission_id: str) -> dict[str, object]:
    return {
        "submission_id": submission_id,
        "concept_id": DIVISION,
        "stage_id": "stage1",
        "correct_count": 2 if passed else 1,
        "passed": passed,
    }


class FakeCache:
    def __init__(self) -> None:
        docs = [
            CachedConcept(DIVISION, "분업/특화", ("분업", "특화"), "설명: 일을 나누는 방식", None),
            CachedConcept(WORKING_POOR, "워킹푸어", ("Working Poor",), "설명: 일해도 가난한 상태", None),
            CachedConcept(GENTRIFICATION, "젠트리피케이션", (), "설명: 상권 변화로 원주민이 밀려나는 현상", None),
            CachedConcept(DEMAND, "수요의 법칙", ("Law of Demand",), "설명: 가격과 수요량의 관계", None),
            CachedConcept(INFLATION, "인플레이션", (), "설명: 물가가 지속해서 오르는 현상", None),
            CachedConcept(DEFLATION, "디플레이션", (), "설명: 물가가 지속해서 내리는 현상", None),
            CachedConcept(
                EIGHTY_EIGHT,
                "88만원세대",
                (),
                "설명: 불안정한 일자리와 낮은 소득을 겪는 청년 세대를 가리키는 말",
                None,
            ),
            CachedConcept(LONGEVITY, "장수리스크", (), "설명: 오래 살며 필요한 자금이 늘어나는 위험", None),
        ]
        self._docs = {doc.concept_id: doc for doc in docs}

    def get(self, concept_id: str) -> CachedConcept | None:
        return self._docs.get(concept_id)

    def values(self) -> tuple[CachedConcept, ...]:
        return tuple(self._docs.values())


def _doc(
    concept_id: str,
    term: str,
    score: float,
    *,
    stage: str = "stage1",
    images: tuple[str, ...] | None = None,
    aliases: tuple[str, ...] = (),
) -> RetrievedDoc:
    return RetrievedDoc(
        concept_id=concept_id,
        term=term,
        score=score,
        collection="sisa_terms",
        label="시사경제용어사전",
        text=f"{term} 설명",
        images=images,
        stages=(stage,),
        aliases=aliases,
    )


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    def search(self, query: str) -> RetrievalResult:
        self.calls.append(query)
        if self.fail:
            raise RuntimeError("qdrant unavailable")
        if "장수리스크 에 대 해" in query:
            hit = _doc(LONGEVITY, "장수리스크", 0.20)
            return RetrievalResult([], [hit], "low", 0.20)
        if "날씨" in query:
            hit = _doc(DIVISION, "분업/특화", 0.20)
            return RetrievalResult([], [hit], "low", 0.20)
        if "경제상식별칭" in query or "extra 검색" in query:
            hit = _doc(
                EXTRA_TERM,
                "부가경제용어",
                0.72,
                stage="extra",
                aliases=("경제상식별칭",),
            )
            return RetrievalResult([hit], [hit], "high", hit.score)
        if "범위밖별칭" in query:
            hit = _doc(
                EXCLUDED_TERM,
                "비경제용어",
                0.72,
                stage="excluded",
                aliases=("범위밖별칭",),
            )
            return RetrievalResult([hit], [hit], "high", hit.score)
        if "저점수" in query:
            other = _doc(WORKING_POOR, "워킹푸어", 0.58)
            current = _doc(DIVISION, "분업/특화", 0.49)
            return RetrievalResult([other], [other, current], "high", 0.58)
        if "젠트리피케이션" in query:
            hit = _doc(GENTRIFICATION, "젠트리피케이션", 0.72)
        elif "디플레이션" in query:
            hit = _doc(DEFLATION, "디플레이션", 0.73, stage="stage3")
        elif "인플레이션" in query:
            hit = _doc(INFLATION, "인플레이션", 0.74, stage="stage3")
        elif "워킹푸어" in query:
            hit = _doc(WORKING_POOR, "워킹푸어", 0.74)
        elif "88만원세대" in query:
            hit = _doc(EIGHTY_EIGHT, "88만원세대", 0.75)
        elif "수요" in query:
            hit = _doc(
                DEMAND,
                "수요의 법칙",
                0.76,
                stage="stage5",
                images=("https://example.com/demand.png",),
            )
        else:
            hit = _doc(DIVISION, "분업/특화", 0.71)
        return RetrievalResult([hit], [hit], "high", hit.score)


class FakeLLM(LLMAdapter):
    def __init__(self) -> None:
        self.prompts: list[Prompt] = []
        self.judgments: list[tuple[str, str, list[HistoryTurn]]] = []
        self.fail_generate = False
        self.stream_chunks = ["개념을 쉬운 말로 ", "설명합니다."]
        self.stream_error_after: int | None = None
        self.judgment = False

    def generate(self, prompt: Prompt) -> str:
        self.prompts.append(prompt)
        if self.fail_generate:
            raise LLMError("LLM 호출에 실패했습니다.")
        return "개념을 쉬운 말로 설명합니다. 생활 속 예시도 함께 볼 수 있습니다."

    def stream(self, prompt: Prompt):
        self.prompts.append(prompt)
        for index, chunk in enumerate(self.stream_chunks):
            if self.stream_error_after == index:
                raise LLMError("LLM 스트리밍 호출에 실패했습니다.")
            yield chunk
        if self.stream_error_after == len(self.stream_chunks):
            raise LLMError("LLM 스트리밍 호출에 실패했습니다.")

    def judge_relevance(
        self,
        *,
        question: str,
        current_term: str,
        history: list[HistoryTurn],
    ) -> bool:
        self.judgments.append((question, current_term, history))
        return self.judgment


@dataclass
class MessageEnv:
    client: TestClient
    status: SqlConceptStatusService
    store: SqlChatStore
    cache: FakeCache
    retriever: FakeRetriever
    llm: FakeLLM
    settings: Settings


@pytest.fixture
def message_env(status_db) -> MessageEnv:
    settings = make_settings(status_db, simulate_quiz_status=False)
    status = SqlConceptStatusService(settings)
    store = SqlChatStore(settings)
    cache = FakeCache()
    retriever = FakeRetriever()
    llm = FakeLLM()
    app = FastAPI()
    install_learning_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_concept_status_service] = lambda: status
    app.dependency_overrides[get_stage_catalog] = lambda: load_stage_catalog(STAGES_PATH)
    app.dependency_overrides[get_chat_store] = lambda: store
    app.dependency_overrides[get_concept_cache] = lambda: cache
    app.dependency_overrides[get_retriever] = lambda: retriever
    app.dependency_overrides[get_llm_adapter] = lambda: llm
    app.dependency_overrides[get_cached_settings] = lambda: settings
    app.dependency_overrides[get_quiz_service] = lambda: DevQuizService(settings)
    try:
        yield MessageEnv(TestClient(app), status, store, cache, retriever, llm, settings)
    finally:
        status.close()
        store.close()


@pytest.fixture
def scenario_env(status_db) -> MessageEnv:
    settings = make_settings(status_db, simulate_quiz_status=True)
    status = SqlConceptStatusService(settings)
    store = SqlChatStore(settings)
    cache = FakeCache()
    retriever = FakeRetriever()
    llm = FakeLLM()
    app = FastAPI()
    install_learning_error_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_concept_status_service] = lambda: status
    app.dependency_overrides[get_stage_catalog] = lambda: load_stage_catalog(STAGES_PATH)
    app.dependency_overrides[get_chat_store] = lambda: store
    app.dependency_overrides[get_concept_cache] = lambda: cache
    app.dependency_overrides[get_retriever] = lambda: retriever
    app.dependency_overrides[get_llm_adapter] = lambda: llm
    app.dependency_overrides[get_cached_settings] = lambda: settings
    app.dependency_overrides[get_quiz_service] = lambda: DevQuizService(settings)
    try:
        yield MessageEnv(TestClient(app), status, store, cache, retriever, llm, settings)
    finally:
        status.close()
        store.close()


def _messages(store: SqlChatStore) -> list[LearningMessageRow]:
    with Session(store._engine) as session:
        return list(
            session.scalars(
                select(LearningMessageRow).order_by(LearningMessageRow.created_at, LearningMessageRow.message_id)
            ).all()
        )


def _sse_events(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in body.strip().split("\n\n"):
        lines = block.splitlines()
        event = next(line.removeprefix("event: ") for line in lines if line.startswith("event: "))
        data = next(line.removeprefix("data: ") for line in lines if line.startswith("data: "))
        events.append((event, json.loads(data)))
    return events


def _record_completed_quiz(env: MessageEnv, quiz_status: str) -> None:
    record = env.store.create_session(
        user_id=USER,
        stage="stage1",
        concept_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
        status="completed",
    )
    env.store.save_learning_context(
        session_id=record.session_id,
        user_id=USER,
        concept_id=DIVISION,
        payload={},
        quiz_status=quiz_status,  # type: ignore[arg-type]
    )


def test_keyword_starts_session_and_saves_two_rows(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화에 대해 알려줘", "concept_id": DIVISION},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_started"] is True
    assert body["concept"] == {
        "concept_id": DIVISION,
        "term": "분업/특화",
        "stage_id": "stage1",
        "status": STATUS_IN_PROGRESS,
        "attempt": 1,
    }
    assert body["is_related"] is True
    assert body["band"] == "high"
    assert body["top_score"] == 0.71
    assert body["sources"][0]["concept_id"] == DIVISION
    assert body["display_sources"][0]["concept_id"] == DIVISION
    assert "참고한 사전 항목: (분업/특화)" in body["answer"]
    assert body["display_sources"][0]["label"] == "재정경제부_시사경제용어 정보 (공공데이터포털)"
    assert message_env.status.get_statuses(USER, "stage1")[DIVISION] == STATUS_IN_PROGRESS

    rows = _messages(message_env.store)
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].session_id == rows[1].session_id == body["session_id"]
    assert rows[0].is_related is None
    assert rows[1].message_id == body["message_id"]
    assert rows[1].is_related is True
    assert rows[1].latency_ms is not None and rows[1].latency_ms >= 0


def test_free_question_detects_current_stage_concept(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "워킹푸어가 뭐야?"}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["session_started"] is False
    assert body["session_id"] is None
    assert body["concept"] is None
    assert body["suggested_concept"] == {
        "concept_id": WORKING_POOR,
        "term": "워킹푸어",
    }
    assert body["notice"] == (
        "워킹푸어는 이번 스테이지에서 배우는 개념이오. "
        "학습으로 남기려면 아래 버튼을 눌러 시작해 보시오."
    )
    assert message_env.status.get_statuses(USER, "stage1")[WORKING_POOR] == STATUS_NOT_STARTED


def test_free_question_auto_start_can_be_enabled(message_env: MessageEnv) -> None:
    enabled = message_env.settings.model_copy(update={"free_question_auto_start": True})
    message_env.client.app.dependency_overrides[get_cached_settings] = lambda: enabled
    body = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "워킹푸어가 뭐야?"}
    ).json()
    assert body["session_started"] is True
    assert body["concept"]["concept_id"] == WORKING_POOR
    assert body["suggested_concept"] is None


def test_stage5_selection_uses_current_stage(message_env: MessageEnv) -> None:
    message_env.status.set_current_stage(USER, "stage5")
    response = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "수요의 법칙을 알려줘", "concept_id": DEMAND},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["concept"]["stage_id"] == "stage5"
    assert body["sources"][0]["images"] == ["https://example.com/demand.png"]
    assert message_env.status.get_current_stage(USER) == "stage5"
    assert message_env.status.get_statuses(USER, "stage5")[DEMAND] == STATUS_IN_PROGRESS
    assert "Stage 5 심화 학습" in message_env.llm.prompts[-1].instructions


@pytest.mark.parametrize("concept_id", [DEMAND, DIVISION], ids=["other-stage", "passed"])
def test_invalid_selected_concept_returns_409_without_starting_learning(
    message_env: MessageEnv, concept_id: str
) -> None:
    if concept_id == DIVISION:
        force_concept_status(message_env.status, USER, DIVISION, "stage1", STATUS_PASSED)

    response = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "개념을 알려줘", "concept_id": concept_id},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []
    assert message_env.retriever.calls == []


def test_non_current_stage_is_not_auto_detected(message_env: MessageEnv) -> None:
    body = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "수요의 법칙을 알려줘"}
    ).json()
    assert body["session_id"] is None
    assert body["session_started"] is False
    assert message_env.status.get_statuses(USER, "stage5")[DEMAND] == STATUS_NOT_STARTED


def test_active_session_stays_fixed_for_other_concept(message_env: MessageEnv) -> None:
    first = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화에 대해 알려줘", "concept_id": DIVISION},
    ).json()
    second = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "젠트리피케이션이 뭐야?"}
    ).json()
    assert second["session_id"] == first["session_id"]
    assert second["session_started"] is False
    assert second["concept"]["concept_id"] == DIVISION
    assert second["is_related"] is False
    assert message_env.status.get_statuses(USER, "stage1")[GENTRIFICATION] == STATUS_NOT_STARTED
    assert message_env.llm.judgments[-1][0:2] == (
        "젠트리피케이션이 뭐야?",
        "분업/특화",
    )
    assert len(message_env.llm.judgments[-1][2]) == 1
    assert "아직 다루지 않은 새 각도" in message_env.llm.prompts[-1].instructions


def test_repeated_question_prompt_reframes_instead_of_copying_dictionary(
    message_env: MessageEnv,
) -> None:
    first = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={
            "message": "88만원세대에 대해 알려줘",
            "concept_id": EIGHTY_EIGHT,
        },
    ).json()
    second = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "88만원세대에 대해 알려줘"},
    ).json()

    assert first["session_id"] == second["session_id"]
    assert second["is_related"] is True
    first_prompt, second_prompt = message_env.llm.prompts[-2:]
    for principle in (
        "핵심 정의와 사실은 제공된 사전 근거와 어긋나지 않게",
        "사전 문장을 그대로 옮기지 말고",
        "핵심 의미 → 왜 중요한지 → 학습자의 생활과의 연결",
        "구체적인 숫자·날짜·최신 통계·특정 기업·인물",
        "일반적인 경제 지식",
    ):
        assert principle in first_prompt.instructions
    assert "한 문장 이하로 짧게 언급" in second_prompt.instructions
    assert "원인·영향·비슷한 개념과의 차이·적용 상황" in second_prompt.instructions
    assert "이전 답변의 숫자·유래·생활 예시를 반복하지" in second_prompt.instructions
    assert "개념을 쉬운 말로 설명합니다." in second_prompt.input


def test_answer_removes_markdown_emoji_and_model_source_line(
    message_env: MessageEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        message_env.llm,
        "generate",
        lambda prompt: "**분업**은 일을 나누는 방식이오. 💡 ^^\n\n출처: 시사경제용어사전",
    )
    body = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화에 대해 알려줘", "concept_id": DIVISION},
    ).json()
    assert body["answer"] == (
        "분업은 일을 나누는 방식이오.\n\n"
        "핵심 정의 출처: 재정경제부_시사경제용어 정보 (공공데이터포털) (분업/특화)"
    )
    assert _messages(message_env.store)[-1].content == body["answer"]


def test_blocked_request_skips_search_llm_and_learning_state(message_env: MessageEnv) -> None:
    body = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "금융사기에 사용할 허위 수익 인증서를 만들어 줘.", "concept_id": DIVISION},
    ).json()
    assert body["safety_level"] == "BLOCK"
    assert "실행 방법은 안내할 수 없소" in body["answer"]
    assert body["session_id"] is None
    assert body["sources"] == []
    assert message_env.retriever.calls == []
    assert message_env.llm.prompts == []
    assert message_env.status.get_statuses(USER, "stage1")[DIVISION] == STATUS_NOT_STARTED
    rows = _messages(message_env.store)
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].content == "[안전 정책에 따라 처리된 요청]"


def test_review_returns_education_without_recommendation(message_env: MessageEnv) -> None:
    body = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "내 돈을 전부 넣을 종목 하나만 골라 줘."},
    ).json()
    assert body["safety_level"] == "REVIEW"
    assert "손실을 감당할 범위" in body["answer"]
    assert body["session_id"] is None
    assert message_env.retriever.calls == []
    assert message_env.llm.prompts == []


def test_personal_investment_and_loan_answers_show_disclaimer_once(message_env: MessageEnv) -> None:
    investment = message_env.client.post(
        "/learning/messages", headers=HEADERS,
        json={"message": "특정 주식을 지금 사도 될까?"},
    ).json()
    loan = message_env.client.post(
        "/learning/messages", headers=HEADERS,
        json={"message": "내 소득에 맞는 대출상품 추천해 줘."},
    ).json()
    assert investment["safety_level"] == loan["safety_level"] == "REVIEW"
    assert investment["answer"].count("AI 작성, 투자 조언 아님") == 1
    assert loan["answer"].count("AI 작성, 투자 조언 아님") == 1
    assert "손실을 감당할 범위" in investment["answer"]
    assert "상환 가능 금액" in loan["answer"]
    assert message_env.retriever.calls == []
    assert message_env.llm.prompts == []


def test_educational_answers_do_not_show_disclaimer(message_env: MessageEnv) -> None:
    for question in ("투자가 뭐야?", "ETF와 펀드의 차이가 뭐야?"):
        body = message_env.client.post(
            "/learning/messages", headers=HEADERS, json={"message": question}
        ).json()
        assert body["safety_level"] == "ALLOW"
        assert "AI 작성, 투자 조언 아님" not in body["answer"]


def test_specific_product_risk_answer_shows_disclaimer_only_once(
    message_env: MessageEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        message_env.llm, "generate",
        lambda prompt: "KODEX 200 ETF는 가격 변동과 수수료 위험이 있소.\nAI 작성, 투자 조언 아님",
    )
    body = message_env.client.post(
        "/learning/messages", headers=HEADERS,
        json={"message": "KODEX 200 ETF의 투자 위험을 다른 상품과 비교해 줘."},
    ).json()
    assert body["safety_level"] == "ALLOW"
    assert body["answer"].count("AI 작성, 투자 조언 아님") == 1
    assert _messages(message_env.store)[-1].content == body["answer"]


def test_review_stream_and_blocked_answer_handle_disclaimer(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/learning/messages/stream", headers=HEADERS,
        json={"message": "특정 주식을 지금 사도 될까?"},
    )
    events = _sse_events(response.text)
    assert [event for event, _ in events] == ["token", "done"]
    assert events[0][1]["delta"].count("AI 작성, 투자 조언 아님") == 1
    assert _messages(message_env.store)[-1].content == events[0][1]["delta"]
    blocked = message_env.client.post(
        "/learning/messages", headers=HEADERS,
        json={"message": "금융사기 실행 방법을 알려 줘."},
    ).json()
    assert blocked["safety_level"] == "BLOCK"
    assert "AI 작성, 투자 조언 아님" not in blocked["answer"]


def test_sensitive_input_is_redacted_in_search_and_storage(message_env: MessageEnv) -> None:
    body = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "복리의 의미를 설명해 줘. 인증번호: 123456"},
    ).json()
    assert body["safety_level"] == "ALLOW"
    assert "123456" not in message_env.retriever.calls[0]
    assert "123456" not in message_env.llm.prompts[-1].input
    assert "123456" not in _messages(message_env.store)[0].content


def test_blocked_stream_sends_safe_answer_and_done(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/learning/messages/stream",
        headers=HEADERS,
        json={"message": "다른 사람의 은행 인증번호를 알아내는 방법을 알려 줘."},
    )
    events = _sse_events(response.text)
    assert [event for event, _ in events] == ["token", "done"]
    assert "실행 방법은 안내할 수 없소" in events[0][1]["delta"]
    assert events[1][1]["safety_level"] == "BLOCK"
    assert _messages(message_env.store)[0].content == "[안전 정책에 따라 처리된 요청]"


@pytest.mark.parametrize(
    ("mode", "expected_instruction", "expected_source"),
    [
        (
            "dictionary_only",
            "사실·숫자·정의는 제공된 사전 근거를 따르되",
            "출처: 재정경제부_시사경제용어 정보 (공공데이터포털)",
        ),
        (
            "dictionary_plus",
            "배경, 이런 현상이 생기는 이유, 생활 사례, 관련 개념과의 연결",
            "핵심 정의 출처: 재정경제부_시사경제용어 정보 (공공데이터포털) (분업/특화)",
        ),
        (
            "free",
            "제공된 사전은 참고 자료로만 사용",
            None,
        ),
    ],
)
def test_answer_knowledge_modes_control_prompt_and_source_label(
    message_env: MessageEnv,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_instruction: str,
    expected_source: str | None,
) -> None:
    settings = message_env.settings.model_copy(update={"answer_knowledge_mode": mode})
    message_env.client.app.dependency_overrides[get_cached_settings] = lambda: settings
    def generate(prompt: Prompt) -> str:
        message_env.llm.prompts.append(prompt)
        return "분업은 일을 나누는 방식이오."
    monkeypatch.setattr(message_env.llm, "generate", generate)

    body = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화에 대해 알려줘", "concept_id": DIVISION},
    ).json()

    prompt = message_env.llm.prompts[-1].instructions
    assert expected_instruction in prompt
    if mode == "dictionary_plus":
        assert "출처와 일반 경제 지식 사용 안내는 서버가" in prompt
        assert "3~5문장" in prompt
    if expected_source is None:
        assert "출처:" not in body["answer"]
    else:
        assert expected_source in body["answer"]


def test_answer_knowledge_mode_expands_detailed_questions(
    message_env: MessageEnv,
) -> None:
    settings = message_env.settings.model_copy(
        update={"answer_knowledge_mode": "dictionary_plus"}
    )
    message_env.client.app.dependency_overrides[get_cached_settings] = lambda: settings
    message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화가 왜 생기는지 더 자세히 알려줘", "concept_id": DIVISION},
    )
    assert "충분히 자세히 답하고" in message_env.llm.prompts[-1].instructions


def test_comparison_question_uses_llm_and_is_related(message_env: MessageEnv) -> None:
    message_env.status.set_current_stage(USER, "stage3")
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "인플레이션을 알려줘", "concept_id": INFLATION},
    ).json()
    message_env.llm.judgment = True
    compared = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "디플레이션이랑 뭐가 달라?"},
    ).json()
    assert compared["session_id"] == started["session_id"]
    assert compared["is_related"] is True
    assert message_env.llm.judgments[-1][0:2] == (
        "디플레이션이랑 뭐가 달라?",
        "인플레이션",
    )
    assert len(message_env.llm.judgments[-1][2]) == 1
    assert message_env.status.get_statuses(USER, "stage3")[DEFLATION] == STATUS_NOT_STARTED

    completed = message_env.client.post(
        f"/learning/sessions/{started['session_id']}/complete",
        headers=_complete_headers("comparison-complete"),
    ).json()
    assert completed["mentioned_concepts"] == [
        {"concept_id": DEFLATION, "term": "디플레이션"}
    ]


def test_relearn_first_other_concept_is_unrelated(message_env: MessageEnv) -> None:
    message_env.status.mark_in_progress(USER, DIVISION, "stage1")
    _record_completed_quiz(message_env, "failed")
    body = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "젠트리피케이션이 뭐야?", "concept_id": DIVISION},
    ).json()
    assert body["session_started"] is True
    assert body["concept"]["concept_id"] == DIVISION
    assert body["concept"]["attempt"] == 2
    assert body["is_related"] is False
    assert message_env.status.get_statuses(USER, "stage1")[GENTRIFICATION] == STATUS_NOT_STARTED


def test_relearn_rejects_other_selected_keyword_before_search(message_env: MessageEnv) -> None:
    message_env.status.mark_in_progress(USER, DIVISION, "stage1")
    _record_completed_quiz(message_env, "failed")
    response = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "워킹푸어가 뭐야?", "concept_id": WORKING_POOR},
    )
    assert response.status_code == 409
    assert message_env.retriever.calls == []
    assert _messages(message_env.store) == []


def test_quiz_pending_ignores_selected_keyword_and_saves_free_pair(message_env: MessageEnv) -> None:
    message_env.status.mark_in_progress(USER, DIVISION, "stage1")
    _record_completed_quiz(message_env, "pending")
    response = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "수요의 법칙을 알려줘", "concept_id": DEMAND},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["session_id"] is None
    assert body["session_started"] is False
    assert body["is_related"] is False
    assert message_env.status.get_statuses(USER, "stage5")[DEMAND] == STATUS_NOT_STARTED
    assert all(row.session_id is None for row in _messages(message_env.store))


def test_quiz_result_rejects_active_session(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()
    response = message_env.client.post(
        f"/learning/sessions/{started['session_id']}/quiz-result",
        headers=HEADERS,
        json=_quiz_result_body(True, "active-session-result"),
    )
    assert response.status_code == 409
    assert "완료된 학습" in response.json()["message"]


def test_quiz_result_rejects_second_result(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()
    session_id = started["session_id"]
    assert message_env.client.post(
        f"/learning/sessions/{session_id}/complete",
        headers=_complete_headers("second-result-complete"),
    ).status_code == 200
    assert message_env.client.post(
        f"/learning/sessions/{session_id}/quiz-result",
        headers=HEADERS,
        json=_quiz_result_body(False, "first-failed-result"),
    ).status_code == 200
    repeated = message_env.client.post(
        f"/learning/sessions/{session_id}/quiz-result",
        headers=HEADERS,
        json=_quiz_result_body(True, "second-result"),
    )
    assert repeated.status_code == 409
    assert "이미 퀴즈 결과" in repeated.json()["message"]
    assert message_env.store.get_learning_context(USER, session_id).quiz_status == "failed"  # type: ignore[union-attr]


def test_complete_is_idempotent_and_requires_key(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()
    path = f"/learning/sessions/{started['session_id']}/complete"

    missing = message_env.client.post(path, headers=HEADERS)
    assert missing.status_code == 422
    assert missing.json()["code"] == "validation_error"
    assert missing.headers["X-Request-ID"] == missing.json()["request_id"]

    headers = _complete_headers("stable-completion-key")
    first = message_env.client.post(path, headers=headers)
    quiz = message_env.client.post(
        f"/learning/sessions/{started['session_id']}/quiz-result",
        headers=HEADERS,
        json=_quiz_result_body(False, "idempotent-complete-failed"),
    )
    assert quiz.status_code == 200
    assert quiz.json()["quiz_status"] == "failed"
    second = message_env.client.post(path, headers=headers)
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert second.json()["quiz_status"] == "pending"
    assert first.json()["completed_at"].endswith(("Z", "+00:00"))


def test_complete_missing_session_returns_404(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/learning/sessions/missing/complete",
        headers=_complete_headers("missing-session"),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_complete_already_completed_session_returns_409(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()
    path = f"/learning/sessions/{started['session_id']}/complete"
    first = message_env.client.post(path, headers=_complete_headers("first-completion"))
    repeated = message_env.client.post(path, headers=_complete_headers("new-completion-key"))

    assert first.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["code"] == "conflict"


def test_complete_rejects_another_session_while_quiz_is_pending(
    message_env: MessageEnv,
) -> None:
    _record_completed_quiz(message_env, "pending")
    active = message_env.store.create_session(
        user_id=USER,
        stage="stage1",
        concept_id=WORKING_POOR,
        term="워킹푸어",
        attempt=1,
        start_type="keyword",
    )

    response = message_env.client.post(
        f"/learning/sessions/{active.session_id}/complete",
        headers=_complete_headers("other-session-pending-quiz"),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert message_env.store.get_session(USER, active.session_id).status == "active"
    assert message_env.store.get_learning_context(USER, active.session_id) is None


def test_quiz_service_error_keeps_completion_unstored(message_env: MessageEnv) -> None:
    class FailingQuizService(DevQuizService):
        def create_quiz_set(self, **kwargs):
            raise QuizServiceError("quiz unavailable")

    message_env.client.app.dependency_overrides[get_quiz_service] = lambda: FailingQuizService(
        message_env.settings
    )
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()
    session_id = started["session_id"]

    response = message_env.client.post(
        f"/learning/sessions/{session_id}/complete",
        headers=_complete_headers("quiz-service-error"),
    )

    assert response.status_code == 502
    assert response.json()["code"] == "external_service_error"
    assert message_env.store.get_session(USER, session_id).status == "active"
    assert message_env.store.get_learning_context(USER, session_id) is None
    assert len(_messages(message_env.store)) == 2


def test_error_response_has_request_id_and_stable_shape(message_env: MessageEnv) -> None:
    response = message_env.client.get(
        "/learning/sessions/missing", headers={**HEADERS, "X-Request-ID": "request-123"}
    )
    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "request-123"
    assert response.json() == {
        "code": "not_found",
        "message": "세션을 찾을 수 없습니다.",
        "request_id": "request-123",
    }


def test_low_band_has_no_sources_and_keeps_score(message_env: MessageEnv) -> None:
    body = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "오늘 날씨 어때?"}
    ).json()
    assert body["band"] == "low"
    assert body["top_score"] == 0.2
    assert body["sources"] == []
    assert body["display_sources"] == []
    assert body["session_id"] is None
    assert "경제 학습 범위 밖" not in body["answer"]
    assert "핵심 정의 출처" not in body["answer"]
    assert "참고한 사전 항목" not in body["answer"]
    assert body["notice"] == "이 물음은 학당의 경제 공부 범위 밖이라 사전의 근거 없이 답하였소."
    assert "친절한 훈장" in message_env.llm.prompts[-1].instructions
    assert "하오체(~이오, ~하오)" in message_env.llm.prompts[-1].instructions


def test_modern_tone_uses_haeyo_prompt_and_notice(message_env: MessageEnv) -> None:
    modern = message_env.settings.model_copy(update={"chat_tone": "modern"})
    message_env.client.app.dependency_overrides[get_cached_settings] = lambda: modern

    body = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "오늘 날씨 어때?"}
    ).json()

    assert "경제 학습 범위 밖" not in body["answer"]
    assert body["notice"] == "이 질문은 학당의 경제 공부 범위 밖이라 사전의 근거 없이 답했어요."
    assert "해요체(~예요, ~해요)" in message_env.llm.prompts[-1].instructions
    assert "~입니다와 해요체를 섞지 마세요" in message_env.llm.prompts[-1].instructions


def test_chat_emoji_setting_does_not_enable_emphasis(message_env: MessageEnv) -> None:
    message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "오늘 날씨 어때?"}
    )
    default_prompt = message_env.llm.prompts[-1].instructions
    assert "이모지와 이모티콘을 사용하지 마세요" in default_prompt

    enabled = message_env.settings.model_copy(update={"chat_emoji": True})
    message_env.client.app.dependency_overrides[get_cached_settings] = lambda: enabled
    message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "오늘 날씨는?"}
    )
    enabled_prompt = message_env.llm.prompts[-1].instructions
    assert "이모지와 이모티콘을 사용하지 마세요" in enabled_prompt


def test_notice_for_other_stage_is_returned_inside_active_session(
    message_env: MessageEnv,
) -> None:
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()
    body = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "인플레이션에 대해 알려줘"}
    ).json()

    assert body["session_id"] == started["session_id"]
    assert body["concept"]["concept_id"] == DIVISION
    assert body["notice"] == (
        "인플레이션을 궁금해하는 그대의 배움의 자세, 참으로 감탄스럽소! 다만 이 개념은 "
        "지금 공부하는 사회경제현상과 소비생활이 아니라 거시경제와 통화·재정정책에서 배우는 것이라, "
        "이번 스테이지 성장과 퀴즈에는 반영되지 않소. 훗날 그 스테이지에 이르면 다시 도전해 보시겠소?"
    )
    assert message_env.status.get_statuses(USER, "stage3")[INFLATION] == STATUS_NOT_STARTED


def test_notice_for_passed_current_stage_concept(scenario_env: MessageEnv) -> None:
    scenario_env.status.mark_in_progress(USER, DIVISION, "stage1")
    force_concept_status(scenario_env.status, USER, DIVISION, "stage1", "passed")

    body = scenario_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "분업/특화를 복습할래"}
    ).json()

    assert body["session_id"] is None
    assert body["notice"] == "분업/특화는 이미 통과한 개념이오. 복습은 언제든 환영하오!"
    assert scenario_env.status.get_statuses(USER, "stage1")[DIVISION] == STATUS_PASSED


def test_extra_and_excluded_notice_require_explicit_term_or_alias(
    message_env: MessageEnv,
) -> None:
    extra = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "경제상식별칭을 설명해줘"}
    ).json()
    excluded = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "범위밖별칭을 설명해줘"}
    ).json()
    incidental = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "extra 검색 결과만 비슷한 질문"}
    ).json()

    assert extra["notice"] == (
        "부가경제용어는 학당의 정규 과정에는 없지만, 알아두면 쓸모 있는 경제 상식이오! "
        "다만 성장과 퀴즈에는 반영되지 않소."
    )
    assert excluded["notice"] == (
        "비경제용어는 경제 학습 범위 밖의 용어라, 성장과 퀴즈에는 반영되지 않소."
    )
    assert "경제 학습 범위 밖 용어" not in excluded["answer"]
    assert incidental["notice"] is None


def test_retrieval_failure_returns_502_without_writes(message_env: MessageEnv) -> None:
    message_env.retriever.fail = True
    response = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    )
    assert response.status_code == 502
    assert message_env.status.get_in_progress_concept(USER, "stage1") is None
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []


def test_blank_free_question_returns_validation_error(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "   "}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert message_env.retriever.calls == []
    assert _messages(message_env.store) == []


@pytest.mark.parametrize("path", ["/learning/messages", "/learning/messages/stream"])
@pytest.mark.parametrize("tone, expected", [
    ("hao", "질문은 500자 이내로 적어 주시오"),
    ("modern", "질문은 500자 이내로 입력해 주세요"),
])
def test_question_length_boundary_and_no_writes_on_rejection(
    message_env: MessageEnv, path: str, tone: str, expected: str
) -> None:
    message_env.settings.chat_tone = tone
    too_long = message_env.client.post(
        path, headers=HEADERS, json={"message": "가" * 501, "concept_id": DIVISION}
    )
    assert too_long.status_code == 422
    assert too_long.json() == {
        "code": "validation_error",
        "message": expected,
        "request_id": too_long.headers["X-Request-ID"],
    }
    assert message_env.retriever.calls == []
    assert message_env.store.get_active_session(USER) is None
    assert message_env.status.get_statuses(USER, "stage1")[DIVISION] == STATUS_NOT_STARTED
    assert _messages(message_env.store) == []

    accepted = message_env.client.post(
        path, headers=HEADERS, json={"message": "가" * 500, "concept_id": DIVISION}
    )
    assert accepted.status_code == 200
    if path.endswith("stream"):
        assert "event: done" in accepted.text
    else:
        assert accepted.json()["session_id"]
    assert len(_messages(message_env.store)) == 2


@pytest.mark.parametrize("path", ["/learning/messages", "/learning/messages/stream"])
def test_question_limit_uses_config_and_ignores_whitespace(
    message_env: MessageEnv, path: str
) -> None:
    message_env.settings.max_question_chars = 4
    accepted = message_env.client.post(path, headers=HEADERS, json={"message": " 가 나 다 라 "})
    assert accepted.status_code == 200
    rejected = message_env.client.post(path, headers=HEADERS, json={"message": "가 나 다 라 마"})
    assert rejected.status_code == 422
    assert rejected.json()["message"] == "질문은 4자 이내로 적어 주시오"
    assert len(_messages(message_env.store)) == 2


@pytest.mark.parametrize("failure", ["search", "llm"])
def test_free_question_external_failure_returns_502_without_writes(
    message_env: MessageEnv, failure: str
) -> None:
    if failure == "search":
        message_env.retriever.fail = True
    else:
        message_env.llm.fail_generate = True

    response = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "오늘 날씨 어때?"}
    )

    assert response.status_code == 502
    assert response.json()["code"] == "external_service_error"
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []


def test_display_sources_keeps_current_hit_and_filters_other_low_score(
    message_env: MessageEnv,
) -> None:
    first = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()
    body = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "저점수 검색 질문"}
    ).json()
    assert body["session_id"] == first["session_id"]
    assert [source["concept_id"] for source in body["sources"]] == [WORKING_POOR]
    assert [source["concept_id"] for source in body["display_sources"]] == [DIVISION]

    rows = _messages(message_env.store)
    assert rows[-1].sources is not None
    assert [source["concept_id"] for source in rows[-1].sources] == [WORKING_POOR]


def test_phase6_learning_quiz_and_relearning_scenario(scenario_env: MessageEnv) -> None:
    free = scenario_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "오늘 날씨 어때?"}
    ).json()
    assert free["session_id"] is None

    first = scenario_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화에 대해 알려줘", "concept_id": DIVISION},
    ).json()
    session1 = first["session_id"]

    related = scenario_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화는 왜 효율적인가요?"},
    ).json()
    assert related["is_related"] is True
    unrelated = scenario_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "젠트리피케이션이 뭐야?"},
    ).json()
    assert unrelated["is_related"] is False

    completed1_response = scenario_env.client.post(
        f"/learning/sessions/{session1}/complete",
        headers=_complete_headers("scenario-attempt-1"),
    )
    assert completed1_response.status_code == 200
    completed1 = completed1_response.json()
    assert completed1["quiz_status"] == "pending"
    assert completed1["concept"]["status"] == STATUS_IN_PROGRESS
    assert completed1["concept"]["attempt"] == 1
    assert [turn["question"] for turn in completed1["turns"]] == [
        "분업/특화에 대해 알려줘",
        "분업/특화는 왜 효율적인가요?",
        "젠트리피케이션이 뭐야?",
    ]
    assert [turn["is_related"] for turn in completed1["turns"]] == [True, True, False]
    assert completed1["mentioned_concepts"] == [
        {"concept_id": GENTRIFICATION, "term": "젠트리피케이션"}
    ]

    fetched = scenario_env.client.get(
        f"/learning/sessions/{session1}/learning-context", headers=HEADERS
    )
    assert fetched.status_code == 200
    assert fetched.json() == {key: value for key, value in completed1.items() if key != "quiz"}
    contexts = scenario_env.client.get("/learning/learning-contexts", headers=HEADERS).json()
    assert contexts[0]["session_id"] == session1

    failed = scenario_env.client.post(
        f"/learning/sessions/{session1}/quiz-result",
        headers=HEADERS,
        json=_quiz_result_body(False, "scenario-failed"),
    )
    assert failed.status_code == 200
    assert failed.json()["quiz_status"] == "failed"
    assert scenario_env.client.get("/learning/current", headers=HEADERS).json()["mode"] == "relearn"

    relearn = scenario_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 다시 알려줘", "concept_id": DIVISION},
    ).json()
    assert relearn["session_started"] is True
    assert relearn["concept"]["attempt"] == 2
    assert "재학습 2회차" in scenario_env.llm.prompts[-1].instructions
    assert "이전 학습 시도의 최근 대화" in scenario_env.llm.prompts[-1].input
    assert "분업/특화에 대해 알려줘" in scenario_env.llm.prompts[-1].input
    session2 = relearn["session_id"]
    assert scenario_env.client.post(
        f"/learning/sessions/{session2}/complete",
        headers=_complete_headers("scenario-attempt-2"),
    ).status_code == 200

    passed = scenario_env.client.post(
        f"/learning/sessions/{session2}/quiz-result",
        headers=HEADERS,
        json=_quiz_result_body(True, "scenario-passed"),
    )
    assert passed.status_code == 200
    assert passed.json()["quiz_status"] == "passed"
    assert scenario_env.status.get_statuses(USER, "stage1")[DIVISION] == STATUS_PASSED

    concepts = scenario_env.client.get("/learning/concepts", headers=HEADERS).json()
    assert concepts["mode"] == "normal"
    assert [concept["concept_id"] for concept in concepts["concepts"]] == [
        "sisa_1963",
        "sisa_980",
        "sisa_1123",
        "sisa_15",
        "sisa_842",
    ]


def test_complete_requires_related_turn_and_keeps_session_active(
    message_env: MessageEnv,
) -> None:
    message_env.status.mark_in_progress(USER, DIVISION, "stage1")
    session = message_env.store.create_session(
        user_id=USER,
        stage="stage1",
        concept_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    message_env.store.save_message_pair(
        user_id=USER,
        session_id=session.session_id,
        question="젠트리피케이션이 뭐야?",
        answer="다른 개념 설명",
        is_related=False,
        band="high",
        top_score=0.72,
        sources=[],
        latency_ms=1,
    )
    response = message_env.client.post(
        f"/learning/sessions/{session.session_id}/complete",
        headers=_complete_headers("unrelated-complete"),
    )
    assert response.status_code == 400
    assert "최소 1턴" in response.json()["message"]
    assert message_env.store.get_session(USER, session.session_id).status == "active"  # type: ignore[union-attr]


def test_learning_context_is_hidden_from_other_users(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()
    session_id = started["session_id"]
    other_headers = {"X-User-Id": "other-user"}
    assert message_env.client.post(
        f"/learning/sessions/{session_id}/complete",
        headers={**other_headers, "Idempotency-Key": "other-user-complete"},
    ).status_code == 404
    assert message_env.client.post(
        f"/learning/sessions/{session_id}/complete",
        headers=_complete_headers("owner-complete"),
    ).status_code == 200
    assert message_env.client.get(
        f"/learning/sessions/{session_id}/learning-context", headers=other_headers
    ).status_code == 404
    assert message_env.client.post(
        f"/learning/sessions/{session_id}/quiz-result",
        headers=other_headers,
        json=_quiz_result_body(True, "other-user-result"),
    ).status_code == 404


def test_message_history_restores_session_and_free_messages(message_env: MessageEnv) -> None:
    message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "오늘 날씨 어때?"}
    )
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    ).json()

    session_response = message_env.client.get(
        f"/learning/sessions/{started['session_id']}/messages", headers=HEADERS
    )
    assert session_response.status_code == 200
    session_messages = session_response.json()
    assert [item["role"] for item in session_messages] == ["user", "assistant"]
    assert session_messages[0]["display_sources"] == []
    assert session_messages[1]["display_sources"][0]["concept_id"] == DIVISION
    assert all(
        {"role", "content", "is_related", "band", "display_sources", "created_at"}
        <= set(item)
        for item in session_messages
    )

    history = message_env.client.get(
        "/learning/history", params={"limit": 3}, headers=HEADERS
    ).json()
    assert [item["role"] for item in history] == ["assistant", "user", "assistant"]
    assert history[0]["session_id"] is None
    assert history[0]["attempt"] is None
    assert history[0]["concept_id"] is None
    assert history[0]["start_type"] is None
    assert history[1]["session_id"] == started["session_id"]
    assert history[1]["attempt"] == 1
    assert history[1]["concept_id"] == DIVISION
    assert history[1]["start_type"] == "keyword"
    assert history[2]["display_sources"][0]["concept_id"] == DIVISION
    assert [item["created_at"] for item in history] == sorted(
        item["created_at"] for item in history
    )

    hidden = message_env.client.get(
        f"/learning/sessions/{started['session_id']}/messages",
        headers={"X-User-Id": "other-user"},
    )
    assert hidden.status_code == 404


def test_stream_completes_then_persists_and_sends_done_metadata(
    message_env: MessageEnv,
) -> None:
    response = message_env.client.post(
        "/learning/messages/stream",
        headers=HEADERS,
        json={"message": "워킹푸어가 뭐야?", "concept_id": WORKING_POOR},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response.text)
    assert [event for event, _data in events] == ["token", "token", "done"]
    answer = "".join(data["delta"] for event, data in events if event == "token")
    done = events[-1][1]
    assert "answer" not in done
    assert done["session_started"] is True
    assert done["concept"]["concept_id"] == WORKING_POOR
    assert done["display_sources"][0]["concept_id"] == WORKING_POOR
    assert done["message_id"]
    assert done["notice"] is None

    rows = _messages(message_env.store)
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[-1].content == answer
    assert message_env.status.get_statuses(USER, "stage1")[WORKING_POOR] == STATUS_IN_PROGRESS


def test_stream_sends_only_normalized_answer(
    message_env: MessageEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    message_env.llm.stream_chunks = [
        "**분", "업**은 중요하오. 💡", "\n- 생활 속에서도 쓰이오!",
        "\n출처: 시사경제용어사전",
    ]
    monkeypatch.setattr(
        message_env.llm, "generate", lambda _prompt: "".join(message_env.llm.stream_chunks)
    )
    payload = {"message": "분업/특화에 대해 알려줘", "concept_id": DIVISION}
    regular = message_env.client.post(
        "/learning/messages", headers=HEADERS, json=payload
    )
    response = message_env.client.post(
        "/learning/messages/stream",
        headers=HEADERS,
        json=payload,
    )
    events = _sse_events(response.text)
    assert [event for event, _ in events] == ["token", "token", "token", "done"]
    answer = "".join(data["delta"] for event, data in events if event == "token")
    assert answer == (
        "분업은 중요하오.\n생활 속에서도 쓰이오!\n\n"
        "핵심 정의 출처: 재정경제부_시사경제용어 정보 (공공데이터포털) (분업/특화)"
    )
    assert regular.json()["answer"] == answer
    assert _messages(message_env.store)[-1].content == answer


def test_split_utf8_stream_matches_regular_answer_and_storage(
    message_env: MessageEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = "분업은 모멘텀을 만드는 방식이오. 생활에서 변화를 느낄 수 있소."
    encoded = raw.encode("utf-8")
    split = encoded.index("멘".encode("utf-8")) + 1
    message_env.llm.stream_chunks = [
        encoded[:split], encoded[split:split + 1], encoded[split + 1:]
    ]
    monkeypatch.setattr(message_env.llm, "generate", lambda _prompt: raw)
    payload = {"message": "분업/특화에 대해 알려줘", "concept_id": DIVISION}
    regular = message_env.client.post("/learning/messages", headers=HEADERS, json=payload)
    streamed = message_env.client.post("/learning/messages/stream", headers=HEADERS, json=payload)
    events = _sse_events(streamed.text)
    tokens = [data["delta"] for event, data in events if event == "token"]
    assert regular.status_code == streamed.status_code == 200
    assert len(tokens) >= 2
    assert "".join(tokens) == regular.json()["answer"] == _messages(message_env.store)[-1].content
    assert "\ufffd" not in "".join(tokens)
    assert "모멘텀" in "".join(tokens)


def test_replacement_character_in_stored_answer_logs_without_answer_text(
    message_env: MessageEnv, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(message_env.llm, "generate", lambda _prompt: "민감한 본문 모멘\ufffd텀이오.")
    with caplog.at_level(logging.WARNING, logger="chatbot.service"):
        response = message_env.client.post(
            "/learning/messages", headers=HEADERS, json={"message": "분업/특화에 대해 알려줘"}
        )
    assert response.status_code == 200
    assert "Answer contains U+FFFD replacement character before persistence" in caplog.text
    assert "민감한 본문" not in caplog.text


def test_sentence_formatter_is_independent_of_model_chunk_boundaries() -> None:
    raw = "**" + ("긴 설명과 사례를 이어 갑니다 " * 20) + "**.\n출처: 모델이 적은 문구"
    whole = IncrementalAnswerFormatter()
    whole.feed(raw)
    whole.finish()
    pieces = IncrementalAnswerFormatter()
    deltas = []
    for index in range(0, len(raw), 7):
        deltas.extend(pieces.feed(raw[index:index + 7]))
    deltas.extend(pieces.finish())
    assert len(deltas) >= 2
    assert "".join(deltas) == whole.body == pieces.body
    assert "**" not in pieces.body
    assert "출처:" not in pieces.body


@pytest.mark.parametrize(
    "question, answer, docs, expected_prefix, tone",
    [
        (
            "물가는 계속 오르는데 경기는 안 좋고 실업도 늘어나는 상황을 뭐라고 해?",
            "스태그플레이션은 경기 침체와 물가 상승이 함께 나타나는 현상이오.",
            (("sisa_2091", "인플레이션(Inflation)"), ("sisa_1810", "에코플레이션")),
            "참고한 사전 항목:",
            "hao",
        ),
        (
            "CPI 발표가 뭐길래 뉴스에 자주 나와?",
            "CPI는 소비자물가지수라는 뜻이오.",
            (("sisa_2466", "차이나플레이션"), ("sisa_1430", "생활물가지수(CPI for Living Necessaries)")),
            "참고한 사전 항목:",
            "modern",
        ),
        (
            "인플레이션은 뭐야?",
            "인플레이션은 물가가 전반적으로 오르는 현상이오.",
            (("sisa_2091", "인플레이션(Inflation)"), ("sisa_1810", "에코플레이션")),
            "핵심 정의 출처:",
            "hao",
        ),
    ],
)
def test_source_attribution_matches_in_message_and_sse(
    message_env: MessageEnv,
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    answer: str,
    docs: tuple[tuple[str, str], ...],
    expected_prefix: str,
    tone: str,
) -> None:
    message_env.settings.chat_tone = tone
    hits = [_doc(concept_id, term, 0.7) for concept_id, term in docs]
    monkeypatch.setattr(
        message_env.retriever, "search",
        lambda _question: RetrievalResult(hits, hits, "high", 0.7),
    )
    monkeypatch.setattr(message_env.llm, "generate", lambda _prompt: answer)
    message_env.llm.stream_chunks = [answer]
    payload = {"message": question}
    regular = message_env.client.post("/learning/messages", headers=HEADERS, json=payload)
    streamed = message_env.client.post("/learning/messages/stream", headers=HEADERS, json=payload)
    assert regular.status_code == streamed.status_code == 200
    body = regular.json()
    events = _sse_events(streamed.text)
    assert events[0][0] == "token"
    assert events[-1][0] == "done"
    assert "".join(data["delta"] for event, data in events if event == "token") == body["answer"]
    assert expected_prefix in body["answer"]
    assert body["sources"] == events[-1][1]["sources"]
    assert body["display_sources"] == events[-1][1]["display_sources"]
    assert _messages(message_env.store)[-1].content == body["answer"]
    if expected_prefix == "핵심 정의 출처:":
        assert "에코플레이션" not in body["answer"]
    else:
        assert "핵심 정의 출처:" not in body["answer"]
        assert (
            "설명했어요" if tone == "modern" else "설명했소"
        ) in body["answer"]


def test_stream_low_band_sends_notice_only_in_done(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/learning/messages/stream",
        headers=HEADERS,
        json={"message": "오늘 날씨 어때?"},
    )
    events = _sse_events(response.text)
    token_text = "".join(data["delta"] for event, data in events if event == "token")
    done = next(data for event, data in events if event == "done")

    assert "경제 공부 범위 밖" not in token_text
    assert "핵심 정의 출처" not in token_text
    assert "참고한 사전 항목" not in token_text
    assert done["notice"] == (
        "이 물음은 학당의 경제 공부 범위 밖이라 사전의 근거 없이 답하였소."
    )


def test_active_longevity_low_band_uses_current_concept_without_out_of_scope_notice(
    message_env: MessageEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "장수리스크에 대해 알려줘", "concept_id": LONGEVITY},
    )
    assert started.status_code == 200
    session_id = started.json()["session_id"]
    answer = (
        "장수리스크는 오래 살수록 생활비가 더 필요한 위험이오.\n"
        "참고한 사전 항목: (장수리스크)\n"
        "※ 핵심 정의는 일반 경제 지식을 바탕으로 설명했소"
    )
    monkeypatch.setattr(message_env.llm, "generate", lambda _prompt: answer)
    message_env.llm.stream_chunks = [answer]
    spaced = "장 수 리 스 크 에 대 해 알 려 줘 가 가"

    regular = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": spaced}
    )
    streamed = message_env.client.post(
        "/learning/messages/stream", headers=HEADERS, json={"message": spaced}
    )
    assert regular.status_code == streamed.status_code == 200
    body = regular.json()
    events = _sse_events(streamed.text)
    token = "".join(data["delta"] for event, data in events if event == "token")
    done = next(data for event, data in events if event == "done")
    for reply, notice in ((body["answer"], body["notice"]), (token, done["notice"])):
        assert "핵심 정의 출처: 재정경제부_시사경제용어 정보 (공공데이터포털) (장수리스크)" in reply
        assert "참고한 사전 항목" not in reply
        assert "핵심 정의는 일반 경제 지식" not in reply
        assert notice is None
        assert "사전의 근거 없이" not in reply
    assert body["band"] == done["band"] == "low"
    assert body["session_id"] == done["session_id"] == session_id
    assert body["sources"] == done["sources"] == []
    assert body["display_sources"] == done["display_sources"] == []
    assert body["answer"] == token
    assert _messages(message_env.store)[-1].content == token
    assert _messages(message_env.store)[-2].content == spaced
    assert message_env.retriever.calls[-1] == "장수리스크 에 대 해 알 려 줘 가 가"
    assert "현재 학습 개념 문서는 이 관련 질문의 근거" in message_env.llm.prompts[-1].instructions


@pytest.mark.parametrize("follow_up", ["예시 하나만 더 들어줘", "그럼 반대 경우는?"])
def test_termless_follow_up_low_uses_current_concept_with_fake_llm(
    message_env: MessageEnv, monkeypatch: pytest.MonkeyPatch, follow_up: str
) -> None:
    started = message_env.client.post(
        "/learning/messages", headers=HEADERS,
        json={"message": "장수리스크에 대해 알려줘", "concept_id": LONGEVITY},
    )
    assert started.status_code == 200
    message_env.llm.judgment = True
    monkeypatch.setattr(
        message_env.retriever, "search",
        lambda _question: RetrievalResult([], [], "low", 0.2),
    )
    message_env.llm.stream_chunks = [
        "개념을 쉬운 말로 설명합니다. 생활 속 예시도 함께 볼 수 있습니다."
    ]
    body = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": follow_up}
    ).json()
    streamed = message_env.client.post(
        "/learning/messages/stream", headers=HEADERS, json={"message": follow_up}
    )
    events = _sse_events(streamed.text)
    token = "".join(data["delta"] for event, data in events if event == "token")
    done = next(data for event, data in events if event == "done")
    assert body["band"] == "low"
    assert body["is_related"] is True
    assert body["notice"] is None
    assert "핵심 정의 출처: 재정경제부_시사경제용어 정보 (공공데이터포털) (장수리스크)" in body["answer"]
    assert "참고한 사전 항목" not in body["answer"]
    assert body["answer"] == token
    assert done["band"] == "low" and done["is_related"] is True
    assert done["notice"] is None
    assert message_env.llm.judgments[-1][0] == follow_up
    assert "현재 학습 개념 문서는 이 관련 질문의 근거" in message_env.llm.prompts[-1].instructions
    assert "[현재 개념] sisa_2173 장수리스크:" in message_env.llm.prompts[-1].input


def test_unrelated_low_during_learning_keeps_out_of_scope_notice(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/learning/messages", headers=HEADERS,
        json={"message": "장수리스크에 대해 알려줘", "concept_id": LONGEVITY},
    )
    assert started.status_code == 200
    body = message_env.client.post(
        "/learning/messages", headers=HEADERS, json={"message": "오늘 날씨 어때?"}
    ).json()
    assert body["band"] == "low"
    assert body["is_related"] is False
    assert body["notice"] == "이 물음은 학당의 경제 공부 범위 밖이라 사전의 근거 없이 답하였소."
    assert "핵심 정의 출처" not in body["answer"]
    assert "참고한 사전 항목" not in body["answer"]


def test_stream_mid_error_sends_error_without_writes(message_env: MessageEnv) -> None:
    message_env.llm.stream_chunks = ["첫 문장이오.", "다음 문장"]
    message_env.llm.stream_error_after = 1
    response = message_env.client.post(
        "/learning/messages/stream",
        headers=HEADERS,
        json={"message": "워킹푸어가 뭐야?", "concept_id": WORKING_POOR},
    )
    events = _sse_events(response.text)
    assert [event for event, _data in events] == ["token", "error"]
    assert events[0][1]["delta"] == "첫 문장이오."
    assert events[-1][1]["code"] == "external_service_error"
    assert events[-1][1]["message"] == "LLM 스트리밍 호출에 실패했습니다."
    assert events[-1][1]["request_id"]
    assert message_env.status.get_in_progress_concept(USER, "stage1") is None
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []


def test_stream_disconnect_does_not_persist_or_change_status(message_env: MessageEnv) -> None:
    prepared = prepare_message(
        catalog=load_stage_catalog(STAGES_PATH),
        status_service=message_env.status,
        store=message_env.store,
        cache=message_env.cache,  # type: ignore[arg-type]
        retriever=message_env.retriever,  # type: ignore[arg-type]
        llm=message_env.llm,
        settings=message_env.settings,
        user_id=USER,
        request=MessageIn(message="워킹푸어가 뭐야?", concept_id=WORKING_POOR),
    )

    async def consume_until_disconnect() -> list[str]:
        checks = 0

        async def is_disconnected() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 2

        return [
            event
            async for event in stream_message_events(
                prepared=prepared,
                status_service=message_env.status,
                store=message_env.store,
                llm=message_env.llm,
                is_disconnected=is_disconnected,
                request_id="disconnect-request",
            )
        ]

    events = asyncio.run(consume_until_disconnect())
    assert events == []
    assert message_env.status.get_in_progress_concept(USER, "stage1") is None
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []


def test_llm_failure_returns_502_without_writes(message_env: MessageEnv) -> None:
    message_env.llm.fail_generate = True
    response = message_env.client.post(
        "/learning/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "concept_id": DIVISION},
    )
    assert response.status_code == 502
    assert message_env.status.get_in_progress_concept(USER, "stage1") is None
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []
