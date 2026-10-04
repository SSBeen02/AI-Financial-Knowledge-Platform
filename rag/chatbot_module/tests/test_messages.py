from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from chatbot.concepts import STATUS_FAILED, STATUS_UNLEARNED, load_stage_catalog
from chatbot.config import Settings
from chatbot.deps import (
    get_cached_settings,
    get_chat_store,
    get_concept_cache,
    get_concept_status_service,
    get_llm_adapter,
    get_retriever,
    get_stage_catalog,
)
from chatbot.integrations import DevConceptStatusService
from chatbot.llm import LLMAdapter, LLMError
from chatbot.prompts import Prompt
from chatbot.retrieval import CachedConcept, RetrievedDoc, RetrievalResult
from chatbot.router import router
from chatbot.schemas import MessageIn
from chatbot.service import prepare_message, stream_message_events
from chatbot.store import ChatMessageRow, SqlChatStore
from tests.conftest import STAGES_PATH, make_settings

USER = "message-user"
HEADERS = {"X-User-Id": USER}
DIVISION = "sisa_1281"
WORKING_POOR = "sisa_1963"
GENTRIFICATION = "sisa_2309"
DEMAND = "sisa_1552"


class FakeCache:
    def __init__(self) -> None:
        docs = [
            CachedConcept(DIVISION, "분업/특화", ("분업", "특화"), "설명: 일을 나누는 방식", None),
            CachedConcept(WORKING_POOR, "워킹푸어", ("Working Poor",), "설명: 일해도 가난한 상태", None),
            CachedConcept(GENTRIFICATION, "젠트리피케이션", (), "설명: 상권 변화로 원주민이 밀려나는 현상", None),
            CachedConcept(DEMAND, "수요의 법칙", ("Law of Demand",), "설명: 가격과 수요량의 관계", None),
        ]
        self._docs = {doc.doc_id: doc for doc in docs}

    def get(self, doc_id: str) -> CachedConcept | None:
        return self._docs.get(doc_id)

    def values(self) -> tuple[CachedConcept, ...]:
        return tuple(self._docs.values())


def _doc(
    doc_id: str,
    term: str,
    score: float,
    *,
    stage: str = "stage1",
    images: tuple[str, ...] | None = None,
) -> RetrievedDoc:
    return RetrievedDoc(
        doc_id=doc_id,
        term=term,
        score=score,
        collection="sisa_terms",
        label="시사경제용어사전",
        text=f"{term} 설명",
        images=images,
        stages=(stage,),
    )


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail = False

    def search(self, query: str) -> RetrievalResult:
        self.calls.append(query)
        if self.fail:
            raise RuntimeError("qdrant unavailable")
        if "날씨" in query:
            hit = _doc(DIVISION, "분업/특화", 0.20)
            return RetrievalResult([], [hit], "low", 0.20)
        if "저점수" in query:
            other = _doc(WORKING_POOR, "워킹푸어", 0.58)
            current = _doc(DIVISION, "분업/특화", 0.49)
            return RetrievalResult([other], [other, current], "high", 0.58)
        if "젠트리피케이션" in query:
            hit = _doc(GENTRIFICATION, "젠트리피케이션", 0.72)
        elif "워킹푸어" in query:
            hit = _doc(WORKING_POOR, "워킹푸어", 0.74)
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
        self.judgments: list[tuple[str, str]] = []
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

    def judge_relevance(self, *, question: str, current_term: str) -> bool:
        self.judgments.append((question, current_term))
        return self.judgment


@dataclass
class MessageEnv:
    client: TestClient
    status: DevConceptStatusService
    store: SqlChatStore
    cache: FakeCache
    retriever: FakeRetriever
    llm: FakeLLM
    settings: Settings


@pytest.fixture
def message_env(status_db) -> MessageEnv:
    settings = make_settings(status_db, simulate_quiz_status=False)
    status = DevConceptStatusService(settings)
    store = SqlChatStore(settings)
    cache = FakeCache()
    retriever = FakeRetriever()
    llm = FakeLLM()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_concept_status_service] = lambda: status
    app.dependency_overrides[get_stage_catalog] = lambda: load_stage_catalog(STAGES_PATH)
    app.dependency_overrides[get_chat_store] = lambda: store
    app.dependency_overrides[get_concept_cache] = lambda: cache
    app.dependency_overrides[get_retriever] = lambda: retriever
    app.dependency_overrides[get_llm_adapter] = lambda: llm
    app.dependency_overrides[get_cached_settings] = lambda: settings
    try:
        yield MessageEnv(TestClient(app), status, store, cache, retriever, llm, settings)
    finally:
        status.close()
        store.close()


@pytest.fixture
def scenario_env(status_db) -> MessageEnv:
    settings = make_settings(status_db, simulate_quiz_status=True)
    status = DevConceptStatusService(settings)
    store = SqlChatStore(settings)
    cache = FakeCache()
    retriever = FakeRetriever()
    llm = FakeLLM()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_concept_status_service] = lambda: status
    app.dependency_overrides[get_stage_catalog] = lambda: load_stage_catalog(STAGES_PATH)
    app.dependency_overrides[get_chat_store] = lambda: store
    app.dependency_overrides[get_concept_cache] = lambda: cache
    app.dependency_overrides[get_retriever] = lambda: retriever
    app.dependency_overrides[get_llm_adapter] = lambda: llm
    app.dependency_overrides[get_cached_settings] = lambda: settings
    try:
        yield MessageEnv(TestClient(app), status, store, cache, retriever, llm, settings)
    finally:
        status.close()
        store.close()


def _messages(store: SqlChatStore) -> list[ChatMessageRow]:
    with Session(store._engine) as session:
        return list(
            session.scalars(
                select(ChatMessageRow).order_by(ChatMessageRow.created_at, ChatMessageRow.message_id)
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
        doc_id=DIVISION,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
        status="completed",
    )
    env.store.save_learning_context(
        session_id=record.session_id,
        user_id=USER,
        doc_id=DIVISION,
        payload={},
        quiz_status=quiz_status,  # type: ignore[arg-type]
    )


def test_keyword_starts_session_and_saves_two_rows(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화에 대해 알려줘", "selected_doc_id": DIVISION},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_started"] is True
    assert body["concept"] == {
        "doc_id": DIVISION,
        "term": "분업/특화",
        "stage": "stage1",
        "status": STATUS_FAILED,
        "attempt": 1,
    }
    assert body["is_related"] is True
    assert body["band"] == "high"
    assert body["top_score"] == 0.71
    assert body["sources"][0]["doc_id"] == DIVISION
    assert body["display_sources"][0]["doc_id"] == DIVISION
    assert body["answer"].endswith("출처: 시사경제용어사전")
    assert message_env.status.get_statuses(USER, "stage1")[DIVISION] == STATUS_FAILED

    rows = _messages(message_env.store)
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].session_id == rows[1].session_id == body["session_id"]
    assert rows[0].is_related is None
    assert rows[1].message_id == body["message_id"]
    assert rows[1].is_related is True
    assert rows[1].latency_ms is not None and rows[1].latency_ms >= 0


def test_free_question_detects_current_stage_concept(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/chat/messages", headers=HEADERS, json={"message": "워킹푸어가 뭐야?"}
    )
    body = response.json()
    assert response.status_code == 200
    assert body["session_started"] is True
    assert body["concept"]["doc_id"] == WORKING_POOR
    assert message_env.status.get_statuses(USER, "stage1")[WORKING_POOR] == STATUS_FAILED


def test_explicit_stage5_selection_starts_outside_current_stage(message_env: MessageEnv) -> None:
    response = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "수요의 법칙을 알려줘", "selected_doc_id": DEMAND, "stage": "stage5"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["concept"]["stage"] == "stage5"
    assert body["sources"][0]["images"] == ["https://example.com/demand.png"]
    assert message_env.status.get_current_stage(USER) == "stage1"
    assert message_env.status.get_statuses(USER, "stage5")[DEMAND] == STATUS_FAILED


def test_stage5_is_not_auto_detected_from_free_question(message_env: MessageEnv) -> None:
    body = message_env.client.post(
        "/chat/messages", headers=HEADERS, json={"message": "수요의 법칙을 알려줘"}
    ).json()
    assert body["session_id"] is None
    assert body["session_started"] is False
    assert body["concept"] is None
    assert message_env.status.get_statuses(USER, "stage5")[DEMAND] == STATUS_UNLEARNED


def test_active_session_stays_fixed_for_other_concept(message_env: MessageEnv) -> None:
    first = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화에 대해 알려줘", "selected_doc_id": DIVISION},
    ).json()
    second = message_env.client.post(
        "/chat/messages", headers=HEADERS, json={"message": "젠트리피케이션이 뭐야?"}
    ).json()
    assert second["session_id"] == first["session_id"]
    assert second["session_started"] is False
    assert second["concept"]["doc_id"] == DIVISION
    assert second["is_related"] is False
    assert message_env.status.get_statuses(USER, "stage1")[GENTRIFICATION] == STATUS_UNLEARNED


def test_relearn_first_other_concept_is_unrelated(message_env: MessageEnv) -> None:
    message_env.status.mark_failed(USER, DIVISION)
    _record_completed_quiz(message_env, "failed")
    body = message_env.client.post(
        "/chat/messages", headers=HEADERS, json={"message": "젠트리피케이션이 뭐야?"}
    ).json()
    assert body["session_started"] is True
    assert body["concept"]["doc_id"] == DIVISION
    assert body["concept"]["attempt"] == 2
    assert body["is_related"] is False
    assert message_env.status.get_statuses(USER, "stage1")[GENTRIFICATION] == STATUS_UNLEARNED


def test_relearn_rejects_other_selected_keyword_before_search(message_env: MessageEnv) -> None:
    message_env.status.mark_failed(USER, DIVISION)
    _record_completed_quiz(message_env, "failed")
    response = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "워킹푸어가 뭐야?", "selected_doc_id": WORKING_POOR},
    )
    assert response.status_code == 409
    assert message_env.retriever.calls == []
    assert _messages(message_env.store) == []


def test_quiz_pending_ignores_selected_keyword_and_saves_free_pair(message_env: MessageEnv) -> None:
    message_env.status.mark_failed(USER, DIVISION)
    _record_completed_quiz(message_env, "pending")
    response = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "수요의 법칙을 알려줘", "selected_doc_id": DEMAND, "stage": "stage5"},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["session_id"] is None
    assert body["session_started"] is False
    assert body["is_related"] is False
    assert message_env.status.get_statuses(USER, "stage5")[DEMAND] == STATUS_UNLEARNED
    assert all(row.session_id is None for row in _messages(message_env.store))


def test_quiz_result_rejects_active_session(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "selected_doc_id": DIVISION},
    ).json()
    response = message_env.client.post(
        f"/chat/sessions/{started['session_id']}/quiz-result",
        headers=HEADERS,
        json={"passed": True},
    )
    assert response.status_code == 409
    assert "학습을 완료" in response.json()["detail"]


def test_quiz_result_rejects_second_result(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "selected_doc_id": DIVISION},
    ).json()
    session_id = started["session_id"]
    assert message_env.client.post(
        f"/chat/sessions/{session_id}/complete", headers=HEADERS
    ).status_code == 200
    assert message_env.client.post(
        f"/chat/sessions/{session_id}/quiz-result",
        headers=HEADERS,
        json={"passed": False},
    ).status_code == 200
    repeated = message_env.client.post(
        f"/chat/sessions/{session_id}/quiz-result",
        headers=HEADERS,
        json={"passed": True},
    )
    assert repeated.status_code == 409
    assert "이미 퀴즈 결과" in repeated.json()["detail"]
    assert message_env.store.get_learning_context(USER, session_id).quiz_status == "failed"  # type: ignore[union-attr]


def test_low_band_has_no_sources_and_keeps_score(message_env: MessageEnv) -> None:
    body = message_env.client.post(
        "/chat/messages", headers=HEADERS, json={"message": "오늘 날씨 어때?"}
    ).json()
    assert body["band"] == "low"
    assert body["top_score"] == 0.2
    assert body["sources"] == []
    assert body["display_sources"] == []
    assert body["session_id"] is None
    assert "경제 학습 범위 밖 질문" in body["answer"]


def test_retrieval_failure_returns_502_without_writes(message_env: MessageEnv) -> None:
    message_env.retriever.fail = True
    response = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "selected_doc_id": DIVISION},
    )
    assert response.status_code == 502
    assert message_env.status.get_failed_concept(USER) is None
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []


def test_display_sources_keeps_current_hit_and_filters_other_low_score(
    message_env: MessageEnv,
) -> None:
    first = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "selected_doc_id": DIVISION},
    ).json()
    body = message_env.client.post(
        "/chat/messages", headers=HEADERS, json={"message": "저점수 검색 질문"}
    ).json()
    assert body["session_id"] == first["session_id"]
    assert [source["doc_id"] for source in body["sources"]] == [WORKING_POOR]
    assert [source["doc_id"] for source in body["display_sources"]] == [DIVISION]

    rows = _messages(message_env.store)
    assert rows[-1].sources is not None
    assert [source["doc_id"] for source in rows[-1].sources] == [WORKING_POOR]


def test_phase6_learning_quiz_and_relearning_scenario(scenario_env: MessageEnv) -> None:
    first = scenario_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화에 대해 알려줘", "selected_doc_id": DIVISION},
    ).json()
    session1 = first["session_id"]

    related = scenario_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화는 왜 효율적인가요?"},
    ).json()
    assert related["is_related"] is True
    unrelated = scenario_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "젠트리피케이션이 뭐야?"},
    ).json()
    assert unrelated["is_related"] is False

    completed1_response = scenario_env.client.post(
        f"/chat/sessions/{session1}/complete", headers=HEADERS
    )
    assert completed1_response.status_code == 200
    completed1 = completed1_response.json()
    assert completed1["quiz_status"] == "pending"
    assert completed1["concept"]["status"] == STATUS_FAILED
    assert completed1["concept"]["attempt"] == 1
    assert [turn["question"] for turn in completed1["turns"]] == [
        "분업/특화에 대해 알려줘",
        "분업/특화는 왜 효율적인가요?",
    ]
    assert completed1["mentioned_concepts"] == [
        {"doc_id": GENTRIFICATION, "term": "젠트리피케이션"}
    ]

    fetched = scenario_env.client.get(
        f"/chat/sessions/{session1}/learning-context", headers=HEADERS
    )
    assert fetched.status_code == 200
    assert fetched.json() == completed1
    contexts = scenario_env.client.get("/chat/learning-contexts", headers=HEADERS).json()
    assert contexts[0]["session_id"] == session1

    failed = scenario_env.client.post(
        f"/chat/sessions/{session1}/quiz-result",
        headers=HEADERS,
        json={"passed": False},
    )
    assert failed.status_code == 200
    assert failed.json()["quiz_status"] == "failed"
    assert scenario_env.client.get("/chat/state", headers=HEADERS).json()["mode"] == "relearn"

    relearn = scenario_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 다시 알려줘"},
    ).json()
    assert relearn["session_started"] is True
    assert relearn["concept"]["attempt"] == 2
    session2 = relearn["session_id"]
    assert scenario_env.client.post(
        f"/chat/sessions/{session2}/complete", headers=HEADERS
    ).status_code == 200

    passed = scenario_env.client.post(
        f"/chat/sessions/{session2}/quiz-result",
        headers=HEADERS,
        json={"passed": True},
    )
    assert passed.status_code == 200
    assert passed.json()["quiz_status"] == "passed"
    assert scenario_env.status.get_statuses(USER, "stage1")[DIVISION] == "통과"

    concepts = scenario_env.client.get("/chat/concepts", headers=HEADERS).json()
    assert concepts["mode"] == "normal"
    assert [concept["doc_id"] for concept in concepts["concepts"]] == [
        "sisa_1963",
        "sisa_980",
        "sisa_1123",
        "sisa_15",
        "sisa_842",
    ]


def test_complete_requires_related_turn_and_keeps_session_active(
    message_env: MessageEnv,
) -> None:
    message_env.status.mark_failed(USER, DIVISION)
    session = message_env.store.create_session(
        user_id=USER,
        stage="stage1",
        doc_id=DIVISION,
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
        f"/chat/sessions/{session.session_id}/complete", headers=HEADERS
    )
    assert response.status_code == 400
    assert "최소 1턴" in response.json()["detail"]
    assert message_env.store.get_session(USER, session.session_id).status == "active"  # type: ignore[union-attr]


def test_learning_context_is_hidden_from_other_users(message_env: MessageEnv) -> None:
    started = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "selected_doc_id": DIVISION},
    ).json()
    session_id = started["session_id"]
    other_headers = {"X-User-Id": "other-user"}
    assert message_env.client.post(
        f"/chat/sessions/{session_id}/complete", headers=other_headers
    ).status_code == 404
    assert message_env.client.post(
        f"/chat/sessions/{session_id}/complete", headers=HEADERS
    ).status_code == 200
    assert message_env.client.get(
        f"/chat/sessions/{session_id}/learning-context", headers=other_headers
    ).status_code == 404
    assert message_env.client.post(
        f"/chat/sessions/{session_id}/quiz-result",
        headers=other_headers,
        json={"passed": True},
    ).status_code == 404


def test_stream_completes_then_persists_and_sends_done_metadata(
    message_env: MessageEnv,
) -> None:
    response = message_env.client.post(
        "/chat/messages/stream",
        headers=HEADERS,
        json={"message": "워킹푸어가 뭐야?"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response.text)
    assert [event for event, _data in events] == ["token", "token", "token", "done"]
    answer = "".join(data["delta"] for event, data in events if event == "token")
    done = events[-1][1]
    assert "answer" not in done
    assert done["session_started"] is True
    assert done["concept"]["doc_id"] == WORKING_POOR
    assert done["display_sources"][0]["doc_id"] == WORKING_POOR
    assert done["message_id"]

    rows = _messages(message_env.store)
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[-1].content == answer
    assert message_env.status.get_statuses(USER, "stage1")[WORKING_POOR] == STATUS_FAILED


def test_stream_mid_error_sends_error_without_writes(message_env: MessageEnv) -> None:
    message_env.llm.stream_error_after = 1
    response = message_env.client.post(
        "/chat/messages/stream",
        headers=HEADERS,
        json={"message": "워킹푸어가 뭐야?"},
    )
    events = _sse_events(response.text)
    assert [event for event, _data in events] == ["token", "error"]
    assert events[-1][1] == {"detail": "LLM 스트리밍 호출에 실패했습니다."}
    assert message_env.status.get_failed_concept(USER) is None
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
        request=MessageIn(message="워킹푸어가 뭐야?"),
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
            )
        ]

    events = asyncio.run(consume_until_disconnect())
    assert [event for event, _data in _sse_events("".join(events))] == ["token"]
    assert message_env.status.get_failed_concept(USER) is None
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []


def test_llm_failure_returns_502_without_writes(message_env: MessageEnv) -> None:
    message_env.llm.fail_generate = True
    response = message_env.client.post(
        "/chat/messages",
        headers=HEADERS,
        json={"message": "분업/특화를 알려줘", "selected_doc_id": DIVISION},
    )
    assert response.status_code == 502
    assert message_env.status.get_failed_concept(USER) is None
    assert message_env.store.get_active_session(USER) is None
    assert _messages(message_env.store) == []
