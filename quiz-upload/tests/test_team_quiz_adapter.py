"""외부 API 없이 실제 퀴즈 DB·생성 서비스를 통한 연결 계약 검증."""

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from types import ModuleType
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

class QuizServiceError(Exception):
    pass

@dataclass(frozen=True)
class QuizSetResult:
    quiz_set_id: str
    status: str


from app.db import Base
from app.services.quiz_service import QuizService
from app.services.team_quiz import TeamQuizService
from app.services import learning_callbacks

SAMPLE_QUESTIONS = [
    dict(question_index=index, question_type="ox", prompt="분업은 일을 나누는 것이다.",
         choices=[{"key": "O", "text": "맞다"}, {"key": "X", "text": "틀리다"}],
         answer="O", explanation="업무를 나누어 수행한다.")
    for index in (1, 2)
] + [
    dict(question_index=3, question_type="situation", prompt="분업에 해당하는 사례는?",
         choices=[{"key": key, "text": f"사례 {key}"} for key in "ABCD"],
         answer="A", explanation="각자 맡은 업무를 수행한다.")
]


class TeamQuizAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # 유빈님 패키지는 현재 폴더에 없어 공개 계약의 대역으로 호출 경계만 검증한다.
        package = ModuleType("chatbot")
        contract = ModuleType("chatbot.quiz")
        contract.QuizServiceError = QuizServiceError
        contract.QuizSetResult = QuizSetResult
        service = ModuleType("chatbot.service")
        self.result_call = Mock()
        self.failure_call = Mock()
        service.report_quiz_result = self.result_call
        service.report_quiz_generation_failed = self.failure_call
        self.modules = patch.dict(sys.modules, {"chatbot": package, "chatbot.quiz": contract, "chatbot.service": service})
        self.modules.start()
        self.store = object()
        self.status = object()
        learning_callbacks.configure_learning_callbacks(store_provider=lambda: self.store, status_provider=lambda: self.status)
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "quiz.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.scope = patch("app.services.team_quiz.session_scope", self.factory)
        self.scope.start()
        self.inputs = dict(
            user_id="adapter-user", session_id="adapter-session",
            concept_id="sisa_1281", stage_id="stage1",
            learning_context={"concept": {"stage_id": "stage1"}, "turns": []},
            reference_chunk_ids=["sisa_1281"],
        )

    async def asyncTearDown(self):
        self.scope.stop()
        self.modules.stop()
        learning_callbacks.configure_learning_callbacks(store_provider=None, status_provider=None)
        await self.engine.dispose()
        self.temp.cleanup()

    async def test_success_and_duplicate_do_not_regenerate(self):
        calls = []

        async def generate(**kwargs):
            calls.append(kwargs)
            return SAMPLE_QUESTIONS

        adapter = TeamQuizService(asyncio.get_running_loop(), QuizService(generate))
        first = await asyncio.to_thread(adapter.create_quiz_set, **self.inputs)
        second = await asyncio.to_thread(adapter.create_quiz_set, **self.inputs)
        self.assertEqual(first, second)
        self.assertEqual(first.status, "completed")
        self.assertTrue(first.quiz_set_id)
        self.assertEqual(len(calls), 1)

        self.assertEqual(calls[0]["learning_session_id"], self.inputs["session_id"])
        self.assertEqual(calls[0]["learning_context"], self.inputs["learning_context"])
        async with self.factory() as session:
            quiz = await QuizService().get_quiz_set(
                session, quiz_set_id=first.quiz_set_id, user_id="adapter-user",
            )
        self.assertEqual(quiz.stage_id, "stage1")
        self.assertEqual(quiz.concept_id, "sisa_1281")

    async def test_saved_failure_is_returned_without_retry(self):
        calls = []

        async def fail(**kwargs):
            calls.append(kwargs)
            raise RuntimeError("simulated generation failure")

        adapter = TeamQuizService(asyncio.get_running_loop(), QuizService(fail))
        first = await asyncio.to_thread(adapter.create_quiz_set, **self.inputs)
        second = await asyncio.to_thread(adapter.create_quiz_set, **self.inputs)
        self.assertEqual(first.status, "failed")
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)
        self.failure_call.assert_called_once_with(
            store=self.store, user_id="adapter-user", session_id="adapter-session",
        )

    async def test_storage_failure_becomes_contract_error(self):
        def unavailable():
            raise RuntimeError("storage unavailable")

        adapter = TeamQuizService(asyncio.get_running_loop())
        with patch("app.services.team_quiz.session_scope", unavailable):
            with self.assertRaises(QuizServiceError):
                await asyncio.to_thread(adapter.create_quiz_set, **self.inputs)

    async def test_event_loop_call_is_rejected_without_deadlock(self):
        adapter = TeamQuizService(asyncio.get_running_loop())
        with self.assertRaises(QuizServiceError):
            adapter.create_quiz_set(**self.inputs)

    async def test_grading_reports_pass_fail_and_duplicate_submission_id(self):
        async def generate(**kwargs):
            return SAMPLE_QUESTIONS
        adapter = TeamQuizService(asyncio.get_running_loop(), QuizService(generate))
        for passed, choices in [(True, ["O", "O", "A"]), (False, ["X", "X", "B"])]:
            inputs = dict(self.inputs, session_id="grade-" + str(passed))
            created = await asyncio.to_thread(adapter.create_quiz_set, **inputs)
            kwargs = dict(user_id=inputs["user_id"], quiz_set_id=created.quiz_set_id,
                          submitted_answers=[dict(question_index=i+1, answer=a) for i,a in enumerate(choices)],
                          idempotency_key="submission-" + str(passed))
            async with self.factory() as session:
                first = await QuizService().submit_quiz_answers(session, **kwargs)
                second = await QuizService().submit_quiz_answers(session, **kwargs)
            self.assertEqual(first.submission_id, second.submission_id)
            call = self.result_call.call_args.kwargs
            self.assertEqual(call["submission_id"], first.submission_id)
            self.assertEqual(call["user_id"], inputs["user_id"])
            self.assertEqual(call["session_id"], inputs["session_id"])
            self.assertEqual(call["stage_id"], "stage1")
            self.assertEqual(call["passed"], passed)
            self.assertIs(call["store"], self.store)
            self.assertIs(call["status_service"], self.status)

    async def test_stage5_uses_fixed_bank_without_generator(self):
        from app.services.stage5_bank import load_bank, fixed_questions
        from app.services.quiz_service import normalize_questions
        bank = load_bank()
        self.assertEqual(len(bank), 70)
        for concept_id in bank:
            self.assertEqual(len(normalize_questions(fixed_questions(concept_id))), 3)
        async def forbidden(**kwargs):
            raise AssertionError("Stage 5 must not call LLM")
        adapter = TeamQuizService(asyncio.get_running_loop(), QuizService(forbidden))
        inputs = dict(self.inputs, concept_id=next(iter(bank)), stage_id="stage5")
        result = await asyncio.to_thread(adapter.create_quiz_set, **inputs)
        self.assertEqual(result.status, "completed")
