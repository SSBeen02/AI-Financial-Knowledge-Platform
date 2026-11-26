"""내용 검토의 승인/거부 계약과 DB 저장 경계. 외부 API는 호출하지 않는다."""
import asyncio
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import Base
from app.models.quiz import QuizSet
from app.services.quiz_content import (
    CONTENT_REVIEW_PROMPT, CONTENT_REVIEW_TIMEOUT_SECONDS, QuestionContentReview,
    QuizContentError, QuizContentReview, QuizContentReviewUnavailable,
    review_quiz_content, validate_content_review,
)
from app.services.quiz_service import QuizService, normalize_questions


CONTEXT = {"concept": "기회비용", "summary": "기회비용은 포기한 대안 중 가장 가치가 큰 대안의 가치입니다."}


def questions():
    return [
        dict(question_index=1, question_type="ox", prompt="기회비용은 포기한 대안 중 가장 가치가 큰 대안의 가치입니다.",
             choices=[dict(key="O", text="O"), dict(key="X", text="X")], answer="O",
             explanation="포기한 대안 중 가치가 가장 큰 대안을 기준으로 합니다."),
        dict(question_index=2, question_type="ox", prompt="기회비용은 포기한 모든 대안의 가치의 합입니다.",
             choices=[dict(key="O", text="O"), dict(key="X", text="X")], answer="X",
             explanation="모든 대안의 합이 아니라 포기한 대안 중 가장 가치가 큰 대안을 기준으로 합니다."),
        dict(question_index=3, question_type="situation",
             prompt="여러분은 2천만원을 가지고 예금하려고 합니다. 기간과 위험 등 다른 조건은 모두 같습니다. 금리는 저축은행 5%, 은행 3.5%, 우체국 2.5%입니다. 저축은행을 선택했습니다. 이 상황에서 기회비용은 무엇입니까?",
             choices=[dict(key="A", text="저축은행 5% 이자"), dict(key="B", text="은행 3.5% 이자"),
                      dict(key="C", text="우체국 2.5% 이자"), dict(key="D", text="2천만원을 다른 곳에 사용하여 발생할 수 있는 모든 이자")],
             answer="B", explanation="포기한 은행과 우체국 중 은행의 3.5% 이자가 가장 크므로 기회비용에 해당합니다."),
    ]


def verdict():
    return QuizContentReview(questions=[QuestionContentReview(
        question_index=i, correct_choice_keys=[answer], grounded=True, well_posed=True,
        calculation_correct=True, explanation_correct=True, rationale="학습 자료와 문제 조건으로 확인했습니다.",
    ) for i, answer in enumerate(["O", "X", "B"], 1)])


def completion(review=None, *, refusal=None, finish_reason="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=review, refusal=refusal), finish_reason=finish_reason)],
        usage=SimpleNamespace(total_tokens=321), _request_id="req-content-test",
    )


def mock_client(*responses):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.beta.chat.completions.parse.side_effect = list(responses)
    return client


class ContentVerdictTests(unittest.TestCase):
    def test_correct_ox_and_situation_set_is_accepted(self):
        validate_content_review(questions(), verdict())

    def test_wrong_selected_return_and_difference_definition_are_rejected(self):
        bad = questions()
        bad[2]["answer"] = "A"
        bad[2]["explanation"] = "기회비용은 선택한 것과 포기한 것 간의 가치 차이로, 저축은행의 5% 이자가 기회비용으로 인정됩니다."
        result = verdict()
        result.questions[2].explanation_correct = False
        with self.assertRaises(QuizContentError) as raised:
            validate_content_review(bad, result)
        self.assertEqual(raised.exception.issues, [{"question_index": 3, "codes": ["answer_mismatch", "explanation_error"]}])

    def test_checks_apply_to_every_concept_and_question_type(self):
        # 검토 결과의 개념명이나 특정 정답(B)에 기대지 않는 공통 게이트다.
        for index in range(3):
            for field, code in [("grounded", "unsupported_content"), ("well_posed", "ambiguous_conditions"),
                                ("calculation_correct", "calculation_error"), ("explanation_correct", "explanation_error")]:
                with self.subTest(index=index, field=field):
                    review = verdict()
                    setattr(review.questions[index], field, False)
                    with self.assertRaises(QuizContentError) as raised:
                        validate_content_review(questions(), review)
                    self.assertIn(code, raised.exception.issues[0]["codes"])
        q = questions()
        q[0]["answer"] = "X"
        with self.assertRaises(QuizContentError):
            validate_content_review(q, verdict())

    def test_missing_multiple_duplicate_and_unknown_answers_fail(self):
        for keys in [[], ["A", "B"], ["B", "B"], ["E"]]:
            result = verdict()
            result.questions[2].correct_choice_keys = keys
            with self.subTest(keys=keys), self.assertRaises((QuizContentError, QuizContentReviewUnavailable)):
                validate_content_review(questions(), result)
        for indexes in [[1, 2], [1, 2, 2], [1, 2, 4]]:
            result = verdict()
            result.questions = [result.questions[0].model_copy(update={"question_index": i}) for i in indexes]
            with self.assertRaises(QuizContentReviewUnavailable):
                validate_content_review(questions(), result)


class ContentReviewRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_batches_three_normalized_questions_and_uses_no_sdk_retry(self):
        client = mock_client(completion(verdict()))
        context = dict(CONTEXT, previous_questions=[{"answer": "A"}], content_review_feedback=["old"])
        with patch("app.services.quiz_content.load_settings", return_value=SimpleNamespace(openai_api_key="fake", openai_model="test-model")), \
             patch("app.services.quiz_content.AsyncOpenAI", return_value=client) as factory:
            await review_quiz_content(quiz_set_id="test-id", concept_id="opportunity", learning_context=context, questions=normalize_questions(questions()))
        factory.assert_called_once_with(api_key="fake", timeout=CONTENT_REVIEW_TIMEOUT_SECONDS, max_retries=0)
        self.assertEqual(client.beta.chat.completions.parse.await_count, 1)
        kwargs = client.beta.chat.completions.parse.await_args.kwargs
        import json
        payload = json.loads(kwargs["messages"][1]["content"])
        self.assertEqual(len(payload["questions"]), 3)
        self.assertEqual(payload["questions"], normalize_questions(questions()))
        self.assertNotIn("previous_questions", payload["learning_context"])
        self.assertNotIn("content_review_feedback", payload["learning_context"])
        self.assertEqual(kwargs["response_format"], QuizContentReview)
        self.assertIn("직접 풀어", CONTENT_REVIEW_PROMPT)

    async def test_refusal_incomplete_malformed_and_transport_failure_do_not_approve(self):
        responses = [completion(None), completion(verdict(), refusal="refused"),
                     completion(verdict(), finish_reason="length"), SimpleNamespace(choices=[]),
                     ValueError("PRIVATE_RAW_RESPONSE")]
        for response in responses:
            with self.subTest(response=type(response).__name__):
                client = mock_client(response)
                with patch("app.services.quiz_content.load_settings", return_value=SimpleNamespace(openai_api_key="fake", openai_model="test-model")), \
                     patch("app.services.quiz_content.AsyncOpenAI", return_value=client):
                    with self.assertRaises(QuizContentReviewUnavailable) as raised:
                        await review_quiz_content(quiz_set_id="id", concept_id="test", learning_context=CONTEXT, questions=questions())
                self.assertNotIn("PRIVATE_RAW_RESPONSE", str(raised.exception))


class ContentStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quiz-content-")
        self.engine = create_async_engine("sqlite+aiosqlite:///" + (Path(self.temp.name) / "test.db").as_posix())
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.notify = AsyncMock()
        notify_patch = patch("app.services.quiz_service.report_quiz_generation_failed", self.notify)
        notify_patch.start()
        self.addCleanup(notify_patch.stop)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()

    async def create(self, service, *, stage="stage1"):
        async with self.factory() as session:
            created = await service.create_quiz_set(session, user_id="test-user", session_id="session", concept_id="opportunity",
                                                    stage_id=stage, learning_context=CONTEXT)
            saved = await session.get(QuizSet, created.id)
            return created, copy.deepcopy(saved.questions)

    async def test_default_reviewer_rejects_bad_set_then_saves_and_grades_corrected_set(self):
        bad = questions()
        # 통합시험 사진의 문제 조건·정답·해설 오류를 재현한다.
        bad[2]["prompt"] = "여러분은 2천만원을 가지고 저축은행에 예금을 하려고 합니다. 금리는 저축은행이 5%, 은행이 3.5%, 우체국이 2.5%입니다. 안정성을 이유로 저축은행을 선택했습니다. 이 상황에서 기회비용은 무엇입니까?"
        bad[2]["answer"] = "A"
        bad[2]["explanation"] = "기회비용은 선택한 것과 포기한 것 간의 가치 차이로, 저축은행의 5% 이자가 기회비용으로 인정됩니다."
        rejected = verdict()
        rejected.questions[2].explanation_correct = False
        rejected.questions[2].well_posed = False
        rejected.questions[2].rationale = "PRIVATE_REVIEW_REASON"
        repaired_review = verdict()
        repaired_review.questions = repaired_review.questions[2:]
        client = mock_client(completion(rejected), completion(repaired_review))
        generator = AsyncMock(side_effect=[bad, questions()[2:]])
        with patch("app.services.quiz_content.load_settings", return_value=SimpleNamespace(openai_api_key="fake", openai_model="test-model")), \
             patch("app.services.quiz_content.AsyncOpenAI", return_value=client), self.assertLogs("quiz", level="WARNING") as logs:
            service = QuizService(generator)  # custom generator여도 기본 내용 검토를 생략하지 않는다.
            created, stored = await self.create(service)
        self.assertEqual(created.status, "completed")
        self.assertEqual(generator.await_count, 2)
        self.assertEqual(client.beta.chat.completions.parse.await_count, 2)
        self.assertEqual(stored, normalize_questions(questions()))
        feedback = generator.await_args_list[1].kwargs["learning_context"]["content_review_feedback"]
        self.assertIn("answer_mismatch", feedback[0]["codes"])
        self.assertIn("ambiguous_conditions", feedback[0]["codes"])
        self.assertIn(created.id, " ".join(logs.output))
        self.assertNotIn(bad[2]["explanation"], " ".join(logs.output))
        self.assertNotIn("PRIVATE_REVIEW_REASON", str(feedback) + " ".join(logs.output))
        self.notify.assert_not_awaited()
        with patch("app.services.quiz_service.report_quiz_result", AsyncMock()):
            async with self.factory() as session:
                result = await service.submit_quiz_answers(session, user_id="test-user", quiz_set_id=created.id,
                    submitted_answers=[dict(question_index=i, answer=a) for i, a in enumerate(["O", "X", "B"], 1)], idempotency_key="first")
                self.assertEqual(result.correct_count, 3)
                self.assertTrue(result.results[2].is_correct)
    async def test_exhausted_content_errors_never_store_questions_or_change_answer(self):
        bad = questions()
        bad[2]["answer"] = "A"
        async def reviewer(**kwargs):
            review = verdict()
            indexes = {q["question_index"] for q in kwargs["questions"]}
            review.questions = [q for q in review.questions if q.question_index in indexes]
            validate_content_review(kwargs["questions"], review)
        generator = AsyncMock(return_value=bad)
        created, stored = await self.create(QuizService(generator, content_reviewer=reviewer))
        self.assertEqual((created.status, stored), ("failed", []))
        self.assertEqual(generator.await_count, 3)
        self.assertEqual(bad[2]["answer"], "A")
        self.notify.assert_awaited_once_with("session", user_id="test-user")

    async def test_reviewer_unavailable_fails_closed_without_regeneration(self):
        generator = AsyncMock(return_value=questions())
        reviewer = AsyncMock(side_effect=QuizContentReviewUnavailable("검토 불가"))
        created, stored = await self.create(QuizService(generator, content_reviewer=reviewer))
        self.assertEqual((created.status, stored), ("failed", []))
        self.assertEqual(generator.await_count, 1)
        self.notify.assert_awaited_once()

    async def test_review_is_inside_shared_generation_deadline(self):
        cancelled = asyncio.Event()
        async def slow(**kwargs):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        with patch("app.services.quiz_service.GENERATION_TIMEOUT_SECONDS", 0.05):
            created, stored = await self.create(QuizService(AsyncMock(return_value=questions()), content_reviewer=slow))
        self.assertTrue(cancelled.is_set())
        self.assertEqual((created.status, stored), ("failed", []))

    async def test_review_has_its_own_deadline_within_total_budget(self):
        cancelled = asyncio.Event()
        async def slow(**kwargs):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        generator = AsyncMock(return_value=questions())
        with patch("app.services.quiz_service.CONTENT_REVIEW_TIMEOUT_SECONDS", 0.03), \
             patch("app.services.quiz_service.GENERATION_TIMEOUT_SECONDS", 1):
            created, stored = await self.create(QuizService(generator, content_reviewer=slow))
        self.assertTrue(cancelled.is_set())
        self.assertEqual(generator.await_count, 1)
        self.assertEqual((created.status, stored), ("failed", []))

    async def test_stage5_fixed_bank_keeps_offline_contract(self):
        generator, reviewer = AsyncMock(), AsyncMock()
        with patch("app.services.stage5_bank.fixed_questions", return_value=questions()):
            created, stored = await self.create(QuizService(generator, content_reviewer=reviewer), stage="stage5")
        self.assertEqual(created.status, "completed")
        generator.assert_not_awaited()
        reviewer.assert_not_awaited()
        self.assertEqual(stored, normalize_questions(questions()))
