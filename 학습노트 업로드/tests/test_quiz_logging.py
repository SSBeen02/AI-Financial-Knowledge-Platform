"""Checks actual log output, elapsed-time boundaries and prompt rules without paid AI."""
import ast
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db import Base
from app.models.quiz import QuizSet
from app.services.quiz_service import QuizService, QUIZ_SYSTEM_PROMPT

tree = ast.parse((Path(__file__).parent/'test_quizzes.py').read_text(encoding='utf-8-sig'))
SAMPLE = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'SAMPLE_QUESTIONS' for t in n.targets))

class QuizLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='quiz-log-')
        self.engine = create_async_engine('sqlite+aiosqlite:///'+(Path(self.temp.name)/'test.db').as_posix())
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()

    async def create(self, generator, stage='stage1'):
        async with self.factory() as session:
            return await QuizService(generator).create_quiz_set(session,user_id='log-user',session_id='log-session',
                concept_id='log-concept',stage_id=stage,learning_context='PRIVATE_CONTEXT_SENTINEL')

    async def test_success_logs_ids_attempts_and_elapsed_without_context(self):
        with self.assertLogs('quiz',level='INFO') as logs, patch('app.services.quiz_service.time.perf_counter',side_effect=[10,10.125]):
            result = await self.create(AsyncMock(return_value=copy.deepcopy(SAMPLE)))
        self.assertEqual(result.status,'completed')
        text='\n'.join(logs.output)
        for value in [result.id,'concept_id=log-concept','stage_id=stage1','source=dynamic','attempts=1','elapsed_ms=125']:
            self.assertIn(value,text)
        self.assertNotIn('PRIVATE_CONTEXT_SENTINEL',text)

    async def test_failed_generation_logs_and_preserves_failed_state(self):
        notify=AsyncMock()
        with self.assertLogs('quiz',level='ERROR') as logs, patch('app.services.quiz_service.report_quiz_generation_failed',notify):
            result=await self.create(AsyncMock(side_effect=RuntimeError('synthetic-error')))
        self.assertEqual(result.status,'failed')
        notify.assert_awaited_once_with('log-session',user_id='log-user')
        self.assertIn('attempts=1','\n'.join(logs.output))
        self.assertIn('elapsed_ms=','\n'.join(logs.output))
        async with self.factory() as session:
            self.assertEqual((await session.get(QuizSet,result.id)).questions,[])

    async def test_grading_log_records_saved_result_and_excludes_callback_duration(self):
        result=await self.create(AsyncMock(return_value=copy.deepcopy(SAMPLE)))
        async def notify(**kwargs):
            self.assertTrue(any('퀴즈 채점 완료' in x for x in logs.output))
        with self.assertLogs('quiz',level='INFO') as logs, patch('app.services.quiz_service.report_quiz_result',AsyncMock(side_effect=notify)), patch('app.services.quiz_service.time.perf_counter',side_effect=[20,20.25]):
            async with self.factory() as session:
                submitted=await QuizService().submit_quiz_answers(session,user_id='log-user',quiz_set_id=result.id,
                    submitted_answers=[{'question_index':i,'answer':a} for i,a in enumerate(['O','O','B'],1)],idempotency_key='log-key')
        text='\n'.join(logs.output)
        for value in [submitted.submission_id,'correct_count=3','passed=True','elapsed_ms=250']:
            self.assertIn(value,text)

    async def test_stage5_logs_source_without_calling_ai(self):
        generator=AsyncMock(side_effect=AssertionError('AI forbidden'))
        with patch('app.services.stage5_bank.fixed_questions',return_value=copy.deepcopy(SAMPLE)),self.assertLogs('quiz',level='INFO') as logs:
            result=await self.create(generator,'stage5')
        self.assertEqual(result.status,'completed')
        generator.assert_not_awaited()
        self.assertIn('source=stage5 attempts=0','\n'.join(logs.output))

    def test_prompt_explicitly_separates_answers_and_prohibits_recommendations(self):
        self.assertIn('정답은 answer, 해설은 explanation에만',QUIZ_SYSTEM_PROMPT)
        self.assertIn('매수·매도·가입을 권유하는 문장은 쓰지 않습니다',QUIZ_SYSTEM_PROMPT)
