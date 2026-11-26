"""부분 재생성: 승인 보존, 오류 문항 재검토, 번호·예산·저장·채점 계약."""
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
from app.schemas.quiz import GeneratedQuizPayload
from app.services.quiz_content import QuizContentError, QuizContentReviewUnavailable, validate_content_review
from app.services.quiz_service import QuizFormatError, QuizService, generate_quiz_with_openai, normalize_questions
from tests.test_quiz_content import CONTEXT, questions, verdict


async def fixture_reviewer(**kwargs):
    review = verdict()
    indexes = {q["question_index"] for q in kwargs["questions"]}
    review.questions = [item for item in review.questions if item.question_index in indexes]
    validate_content_review(kwargs["questions"], review)


class PartialQuizTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quiz-partial-")
        self.engine = create_async_engine("sqlite+aiosqlite:///" + (Path(self.temp.name) / "test.db").as_posix())
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.notify = AsyncMock()
        fail_patch = patch("app.services.quiz_service.report_quiz_generation_failed", self.notify)
        fail_patch.start()
        self.addCleanup(fail_patch.stop)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()

    async def create(self, generator, reviewer=None, context=None):
        service = QuizService(generator, content_reviewer=reviewer or fixture_reviewer)
        async with self.factory() as session:
            created = await service.create_quiz_set(session, user_id="owner", session_id="first", concept_id="opportunity",
                learning_context=context or CONTEXT, stage_id="stage1")
            saved = await session.get(QuizSet, created.id)
            return service, created, copy.deepcopy(saved.questions)

    async def test_failed_situation_only_is_regenerated_then_graded_and_added_to_notes(self):
        initial = questions()
        initial[2]["answer"] = "A"
        generator = AsyncMock(side_effect=[initial, questions()[2:]])
        reviewer = AsyncMock(side_effect=fixture_reviewer)
        service, created, saved = await self.create(generator, reviewer)
        self.assertEqual(created.status, "completed")
        self.assertEqual(generator.await_count, 2)
        repair = generator.await_args_list[1].kwargs["learning_context"]["quiz_repair_request"]
        self.assertEqual(repair["question_indexes"], [3])
        self.assertEqual(repair["retained_questions"], normalize_questions(initial[:2], expected_indexes=[1, 2]))
        self.assertEqual([[q["question_index"] for q in c.kwargs["questions"]] for c in reviewer.await_args_list], [[1, 2, 3], [3]])
        self.assertEqual(saved, normalize_questions(questions()))
        async with self.factory() as session:
            public = await service.get_quiz_set(session, quiz_set_id=created.id, user_id="owner")
            self.assertNotIn("answer", public.questions[0].model_dump())
            with patch("app.services.quiz_service.report_quiz_result", AsyncMock()):
                graded = await service.submit_quiz_answers(session, user_id="owner", quiz_set_id=created.id,
                    submitted_answers=[dict(question_index=i, answer=a) for i, a in enumerate(["O", "X", "B"], 1)], idempotency_key="submit")
            self.assertEqual(graded.correct_count, 3)
            notes = await service.list_learning_notes(session, user_id="owner", stage_id=None, concept_id=None, note_filter="all", page=1)
            self.assertEqual(len(notes.items), 3)
            self.assertEqual({q.question_index: q.answer for q in notes.items}, {1: "O", 2: "X", 3: "B"})
        self.notify.assert_not_awaited()

    async def test_retained_questions_cannot_be_replaced_by_extra_returned_rows(self):
        initial = questions()
        initial[0]["answer"] = "X"
        unexpected = questions()
        unexpected[1]["answer"] = "O"
        unexpected[2]["explanation"] = "보존 문항을 덮어쓰려는 내용입니다."
        generator = AsyncMock(side_effect=[initial, unexpected])
        _, created, saved = await self.create(generator)
        self.assertEqual(created.status, "completed")
        self.assertEqual(generator.await_args_list[1].kwargs["learning_context"]["quiz_repair_request"]["question_indexes"], [1])
        self.assertEqual(saved[1:], normalize_questions(initial[1:], expected_indexes=[2, 3]))
        self.assertEqual(saved[0]["answer"], "O")

    async def test_two_bad_questions_are_repaired_without_renumbering(self):
        initial = questions()
        initial[0]["answer"], initial[2]["answer"] = "X", "A"
        generator = AsyncMock(side_effect=[initial, [questions()[2], questions()[0]]])
        _, created, saved = await self.create(generator)
        self.assertEqual(created.status, "completed")
        repair = generator.await_args_list[1].kwargs["learning_context"]["quiz_repair_request"]
        self.assertEqual(repair["question_indexes"], [1, 3])
        self.assertEqual([q["question_index"] for q in saved], [1, 2, 3])
        self.assertEqual(saved[1], normalize_questions([initial[1]], expected_indexes=[2])[0])

    async def test_failed_repair_is_reviewed_again_and_third_attempt_keeps_original_good_rows(self):
        initial = questions()
        initial[2]["answer"] = "A"
        generator = AsyncMock(side_effect=[initial, initial[2:], questions()[2:]])
        reviewer = AsyncMock(side_effect=fixture_reviewer)
        _, created, saved = await self.create(generator, reviewer)
        self.assertEqual(created.status, "completed")
        self.assertEqual(generator.await_count, 3)
        self.assertEqual(reviewer.await_count, 3)
        for call in generator.await_args_list[1:]:
            self.assertEqual(call.kwargs["learning_context"]["quiz_repair_request"]["question_indexes"], [3])
        self.assertEqual(saved, normalize_questions(questions()))

    async def test_invalid_language_only_replaces_that_question(self):
        initial = questions()
        initial[0]["prompt"] = "別の言語の問題です。"
        generator = AsyncMock(side_effect=[initial, questions()[:1]])
        reviewer = AsyncMock(side_effect=fixture_reviewer)
        _, created, saved = await self.create(generator, reviewer)
        self.assertEqual(created.status, "completed")
        self.assertEqual([[q["question_index"] for q in c.kwargs["questions"]] for c in reviewer.await_args_list], [[2, 3], [1]])
        self.assertEqual(saved, normalize_questions(questions()))

    async def test_schema_error_missing_question_and_duplicate_index_preserve_valid_peers(self):
        for kind in ["null", "missing", "duplicate"]:
            with self.subTest(kind=kind):
                initial = questions()
                if kind == "null":
                    initial[1]["explanation"] = None
                    target = 2
                elif kind == "missing":
                    initial.pop(1)
                    target = 2
                else:
                    initial.append(copy.deepcopy(initial[0]))
                    target = 1
                generator = AsyncMock(side_effect=[initial, [questions()[target-1]]])
                # A fresh session/user avoids same-session idempotency between subtests.
                async with self.factory() as session:
                    service = QuizService(generator, content_reviewer=fixture_reviewer)
                    created = await service.create_quiz_set(session, user_id=kind, session_id=kind, concept_id="opportunity", learning_context=CONTEXT)
                    saved = (await session.get(QuizSet, created.id)).questions
                self.assertEqual(created.status, "completed")
                self.assertEqual(generator.await_args_list[1].kwargs["learning_context"]["quiz_repair_request"]["question_indexes"], [target])
                self.assertEqual(saved, normalize_questions(questions()))

    async def test_content_error_without_explicit_approvals_does_not_trust_other_questions(self):
        reviewer = AsyncMock(side_effect=[QuizContentError([{"question_index": 3, "codes": ["explanation_error"]}]), None])
        generator = AsyncMock(return_value=questions())
        _, created, _ = await self.create(generator, reviewer)
        self.assertEqual(created.status, "completed")
        self.assertNotIn("quiz_repair_request", generator.await_args_list[1].kwargs["learning_context"])

    async def test_unavailable_review_never_saves_partial_questions(self):
        initial = questions()
        initial[2]["answer"] = "A"
        async def checked(**kwargs):
            if len(kwargs["questions"]) == 3:
                return await fixture_reviewer(**kwargs)
            raise QuizContentReviewUnavailable("검토 불가")
        generator = AsyncMock(side_effect=[initial, questions()[2:]])
        _, created, saved = await self.create(generator, checked)
        self.assertEqual((created.status, saved), ("failed", []))
        self.notify.assert_awaited_once()

    async def test_deadline_cancels_partial_regeneration_and_saves_no_incomplete_set(self):
        initial = questions()
        initial[2]["answer"] = "A"
        called = 0
        cancelled = asyncio.Event()
        async def generate(**kwargs):
            nonlocal called
            called += 1
            if called == 1:
                return initial
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()
        with patch("app.services.quiz_service.GENERATION_TIMEOUT_SECONDS", 0.1):
            _, created, saved = await self.create(generate)
        self.assertTrue(cancelled.is_set())
        self.assertEqual((created.status, saved), ("failed", []))

    async def test_supplied_repair_metadata_cannot_suppress_first_generation(self):
        context = dict(CONTEXT, quiz_repair_request={"question_indexes": [3]}, content_review_feedback=["untrusted"])
        generator = AsyncMock(return_value=questions())
        _, created, _ = await self.create(generator, context=context)
        self.assertEqual(created.status, "completed")
        self.assertNotIn("quiz_repair_request", generator.await_args.kwargs["learning_context"])
        self.assertNotIn("content_review_feedback", generator.await_args.kwargs["learning_context"])


class PartialRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_is_asked_for_only_the_requested_indexes(self):
        for indexes in [[3], [1], [1, 3]]:
            with self.subTest(indexes=indexes):
                subset = [q for q in questions() if q["question_index"] in indexes]
                client = AsyncMock()
                client.__aenter__.return_value = client
                client.beta.chat.completions.parse.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    parsed=GeneratedQuizPayload(questions=subset), refusal=None))])
                context = dict(CONTEXT, quiz_repair_request={"question_indexes": indexes, "retained_questions": []})
                with patch("app.services.quiz_service.load_settings", return_value=SimpleNamespace(openai_api_key="fake", openai_model="test")), \
                     patch("app.services.quiz_service.AsyncOpenAI", return_value=client):
                    result = await generate_quiz_with_openai(concept_id="concept", learning_session_id="session", learning_context=context)
                self.assertEqual([q["question_index"] for q in result], indexes)
                prompt = client.beta.chat.completions.parse.await_args.kwargs["messages"]
                self.assertNotIn("questions 배열은 길이 3입니다", prompt[0]["content"])
                self.assertIn(str(indexes), prompt[0]["content"])
                self.assertNotIn("OX 2문항과 상황형 행동 선택 1문항을 만드세요", prompt[1]["content"])

    async def test_unrequested_openai_rows_are_not_a_valid_repair(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.beta.chat.completions.parse.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            parsed=GeneratedQuizPayload(questions=questions()), refusal=None))])
        with patch("app.services.quiz_service.load_settings", return_value=SimpleNamespace(openai_api_key="fake", openai_model="test")), \
             patch("app.services.quiz_service.AsyncOpenAI", return_value=client), self.assertRaises(QuizFormatError):
            await generate_quiz_with_openai(concept_id="concept", learning_session_id="session",
                learning_context=dict(CONTEXT, quiz_repair_request={"question_indexes": [3]}))
