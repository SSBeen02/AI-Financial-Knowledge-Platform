from __future__ import annotations

from pathlib import Path

import pytest

from chatbot.integrations import SqlConceptStatusService
from chatbot.quiz import DevQuizService, QuizService, QuizSetResult
from chatbot.retrieval import CachedConcept
from chatbot.service import (
    SessionNotFound,
    complete_learning_session,
    report_quiz_generation_failed,
    retry_quiz_generation,
)
from chatbot.store import SqlChatStore
from chatbot.concepts import load_stage_catalog
from chatbot.service import get_chat_state
from tests.conftest import STAGES_PATH, make_settings

USER = "quiz-user"
CONCEPT = "sisa_1281"
STAGE = "stage1"


class OrderedFailureQuizService(QuizService):
    def __init__(
        self,
        *,
        store: SqlChatStore,
        callback_before_return: bool,
        return_failed: bool,
    ) -> None:
        self.store = store
        self.callback_before_return = callback_before_return
        self.return_failed = return_failed

    def create_quiz_set(self, **kwargs: object) -> QuizSetResult:
        if self.callback_before_return:
            report_quiz_generation_failed(
                store=self.store,
                user_id=str(kwargs["user_id"]),
                session_id=str(kwargs["session_id"]),
            )
        return QuizSetResult(
            quiz_set_id="ordered-failure",
            status="failed" if self.return_failed else "pending",
        )


class Cache:
    def get(self, concept_id: str) -> CachedConcept | None:
        if concept_id != CONCEPT:
            return None
        return CachedConcept(
            concept_id=CONCEPT,
            term="분업/특화",
            aliases=(),
            text="분업/특화\n설명: 일을 나누고 전문화하는 경제 원리",
            images=None,
        )

    def values(self) -> list[CachedConcept]:
        concept = self.get(CONCEPT)
        return [concept] if concept is not None else []


def _active_attempt(service: SqlConceptStatusService, store: SqlChatStore) -> str:
    service.mark_in_progress(USER, CONCEPT, STAGE)
    session = store.create_session(
        user_id=USER,
        stage=STAGE,
        concept_id=CONCEPT,
        term="분업/특화",
        attempt=1,
        start_type="keyword",
    )
    store.save_message_pair(
        user_id=USER,
        session_id=session.session_id,
        question="분업/특화가 뭐야?",
        answer="일을 나누는 원리이오.",
        is_related=True,
        band="high",
        top_score=0.9,
        sources=[
            {
                "concept_id": CONCEPT,
                "collection": "sisa_terms",
                "label": "시사경제용어사전",
            }
        ],
        display_sources=[],
        latency_ms=1,
    )
    return session.session_id


def test_completion_returns_nested_quiz_and_replays_same_result(tmp_path: Path) -> None:
    settings = make_settings(tmp_path / "complete.db", simulate_quiz_status=False)
    store = SqlChatStore(settings)
    service = SqlConceptStatusService(settings)
    quiz = DevQuizService(settings)
    try:
        session_id = _active_attempt(service, store)
        kwargs = dict(
            status_service=service,
            store=store,
            cache=Cache(),
            quiz_service=quiz,
            user_id=USER,
            session_id=session_id,
            idempotency_key="completion-key",
        )
        first = complete_learning_session(**kwargs)
        second = complete_learning_session(**kwargs)
        assert first == second
        assert first.quiz.status == "pending"
        assert first.quiz.quiz_set_id
        assert first.reference_chunk_ids == [CONCEPT]
        assert store.get_learning_context(USER, session_id).quiz_status == "pending"
    finally:
        service.close()
        store.close()


def test_generation_failure_and_retry_use_new_completed_session(tmp_path: Path) -> None:
    failed_settings = make_settings(tmp_path / "retry.db", simulate_quiz_status=False).model_copy(
        update={"dev_simulate_quiz_generation_failure": True}
    )
    store = SqlChatStore(failed_settings)
    service = SqlConceptStatusService(failed_settings)
    failed_quiz = DevQuizService(failed_settings)
    normal_quiz = DevQuizService(
        failed_settings.model_copy(update={"dev_simulate_quiz_generation_failure": False})
    )
    try:
        original_id = _active_attempt(service, store)
        completed = complete_learning_session(
            status_service=service,
            store=store,
            cache=Cache(),
            quiz_service=failed_quiz,
            user_id=USER,
            session_id=original_id,
            idempotency_key="failed-completion",
        )
        assert completed.quiz.status == "failed"
        assert store.get_learning_context(USER, original_id).quiz_status == "generation_failed"
        failed_state = get_chat_state(
            load_stage_catalog(STAGES_PATH), service, store, USER
        )
        assert failed_state.mode == "quiz_generation_failed"
        assert failed_state.notice == (
            "퀴즈를 준비하는 중에 문제가 생겼소. 아래 버튼을 눌러 퀴즈를 다시 받아 보시오."
        )

        # 실패 콜백이 두 번 와도 상태 변화는 한 번뿐이다.
        first_callback = report_quiz_generation_failed(
            store=store, user_id=USER, session_id=original_id
        )
        second_callback = report_quiz_generation_failed(
            store=store, user_id=USER, session_id=original_id
        )
        assert first_callback == second_callback

        kwargs = dict(
            status_service=service,
            store=store,
            quiz_service=normal_quiz,
            user_id=USER,
            session_id=original_id,
            idempotency_key="retry-key",
        )
        retried = retry_quiz_generation(**kwargs)
        replay = retry_quiz_generation(**kwargs)
        assert retried == replay
        assert retried.session_id != original_id
        assert retried.attempt == 1
        assert retried.quiz.status == "pending"
        retry_session = store.get_session(USER, retried.session_id)
        assert retry_session is not None
        assert retry_session.start_type == "quiz_retry"
        assert retry_session.status == "completed"
        assert store.get_session_messages(USER, retried.session_id) == []
        retry_context = store.get_learning_context(USER, retried.session_id)
        assert retry_context is not None
        assert retry_context.payload["reference_chunk_ids"] == [CONCEPT]
        assert service.get_concept_status(USER, CONCEPT, STAGE) == "in_progress"
        assert get_chat_state(
            load_stage_catalog(STAGES_PATH), service, store, USER
        ).mode == "quiz_pending"
    finally:
        service.close()
        store.close()


@pytest.mark.parametrize(
    ("callback_timing", "return_failed"),
    [
        pytest.param("before", True, id="callback-before-failed-return"),
        pytest.param("after", True, id="failed-return-before-callback"),
        pytest.param("before", False, id="callback-only"),
        pytest.param("none", True, id="failed-return-only"),
    ],
)
def test_generation_failure_order_always_reaches_one_final_state(
    tmp_path: Path,
    callback_timing: str,
    return_failed: bool,
) -> None:
    settings = make_settings(
        tmp_path / f"failure-order-{callback_timing}-{return_failed}.db",
        simulate_quiz_status=False,
    )
    store = SqlChatStore(settings)
    service = SqlConceptStatusService(settings)
    quiz = OrderedFailureQuizService(
        store=store,
        callback_before_return=callback_timing == "before",
        return_failed=return_failed,
    )
    try:
        session_id = _active_attempt(service, store)
        completion = complete_learning_session(
            status_service=service,
            store=store,
            cache=Cache(),
            quiz_service=quiz,
            user_id=USER,
            session_id=session_id,
            idempotency_key=f"failure-order-{callback_timing}-{return_failed}",
        )
        if callback_timing == "after":
            report_quiz_generation_failed(
                store=store,
                user_id=USER,
                session_id=session_id,
            )

        context = store.get_learning_context(USER, session_id)
        assert context is not None
        assert context.quiz_status == "generation_failed"
        assert completion.quiz.status == ("failed" if return_failed else "pending")
        assert get_chat_state(
            load_stage_catalog(STAGES_PATH), service, store, USER
        ).mode == "quiz_generation_failed"
    finally:
        service.close()
        store.close()


def test_generation_failure_callback_still_rejects_wrong_or_missing_owner(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path / "failure-owner.db", simulate_quiz_status=False)
    store = SqlChatStore(settings)
    service = SqlConceptStatusService(settings)
    try:
        session_id = _active_attempt(service, store)
        with pytest.raises(SessionNotFound):
            report_quiz_generation_failed(
                store=store,
                user_id="another-user",
                session_id=session_id,
            )
        with pytest.raises(SessionNotFound):
            report_quiz_generation_failed(
                store=store,
                user_id=USER,
                session_id="missing-session",
            )
    finally:
        service.close()
        store.close()
