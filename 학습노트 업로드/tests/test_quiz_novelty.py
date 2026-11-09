"""Dynamic re-learning quizzes must reject reused questions."""
import ast
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db import Base
from app.models.quiz import QuizSet
from app.services.quiz_service import DuplicateQuizQuestionError, QuizService, _check_new_questions, normalize_questions

tree = ast.parse((Path(__file__).parent / 'test_quizzes.py').read_text(encoding='utf-8-sig'))
ORIGINAL = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
    and any(isinstance(t, ast.Name) and t.id == 'SAMPLE_QUESTIONS' for t in n.targets))


def alternative():
    value = copy.deepcopy(ORIGINAL)
    for q, text in zip(value, [
        '예금 이자의 계산에서 기간이 같아도 적용하는 방식에 따라 받을 금액이 달라질 수 있소.',
        '시간이 지날수록 원금에만 붙이는 이자와 원리금에 붙이는 이자의 차이를 구분해야 하오.',
        '가입 전에 중도 해지 조건을 읽고 자금 사용 계획과 비교하는 이유는 무엇이오?',
    ]):
        q['prompt'] = text
    return value


class QuizNoveltyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='quiz-novelty-')
        self.engine = create_async_engine('sqlite+aiosqlite:///' + (Path(self.temp.name)/'test.db').as_posix())
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()

    async def create(self, generator, session_id, user='novelty-user', concept='interest'):
        async with self.factory() as session:
            return await QuizService(generator).create_quiz_set(session, user_id=user, session_id=session_id,
                concept_id=concept, stage_id='stage1', learning_context={'concept':{'term':'이자'},'facts':'단리와 복리를 비교한다.'})

    async def test_failed_grade_relearning_rejects_old_set_and_uses_new_set(self):
        old = await self.create(AsyncMock(return_value=copy.deepcopy(ORIGINAL)), 'first')
        with patch('app.services.quiz_service.report_quiz_result', AsyncMock()):
            async with self.factory() as session:
                result = await QuizService().submit_quiz_answers(session, user_id='novelty-user', quiz_set_id=old.id,
                    submitted_answers=[{'question_index':i,'answer':a} for i,a in enumerate(['X','X','A'],1)],
                    idempotency_key='fail-grade')
                self.assertFalse(result.is_passed)
        generator = AsyncMock(side_effect=[copy.deepcopy(ORIGINAL), alternative()])
        created = await self.create(generator, 'relearning')
        self.assertEqual(created.status, 'completed')
        self.assertEqual(generator.await_count, 2)
        self.assertEqual(len(generator.await_args_list[0].kwargs['learning_context']['previous_questions']), 3)
        async with self.factory() as session:
            saved = await session.get(QuizSet, created.id)
            self.assertEqual([q['prompt'] for q in saved.questions], [q['prompt'] for q in alternative()])
            old_saved = await session.get(QuizSet, old.id)
            self.assertEqual([q['prompt'] for q in old_saved.questions], [q['prompt'] for q in normalize_questions(copy.deepcopy(ORIGINAL))])

    async def test_persistent_reuse_fails_without_serving_previous_questions(self):
        await self.create(AsyncMock(return_value=copy.deepcopy(ORIGINAL)), 'old')
        generator = AsyncMock(return_value=copy.deepcopy(ORIGINAL))
        notify = AsyncMock()
        with patch('app.services.quiz_service.report_quiz_generation_failed', notify), patch('app.services.quiz_service.logger.exception'):
            created = await self.create(generator, 'new')
        self.assertEqual(created.status, 'failed')
        self.assertEqual(generator.await_count, 2)
        notify.assert_awaited_once_with('new', user_id='novelty-user')
        async with self.factory() as session:
            self.assertEqual((await session.get(QuizSet, created.id)).questions, [])

    async def test_one_repeated_question_rejects_entire_regenerated_set(self):
        await self.create(AsyncMock(return_value=copy.deepcopy(ORIGINAL)), 'old')
        mixed = alternative()
        mixed[1] = copy.deepcopy(ORIGINAL[0])
        mixed[1]['question_index'] = 2
        generator = AsyncMock(side_effect=[mixed, alternative()])
        created = await self.create(generator, 'new')
        self.assertEqual(created.status, 'completed')
        self.assertEqual(generator.await_count, 2)

    async def test_punctuation_numbers_and_close_rewrites_are_rejected(self):
        for replacement in [ORIGINAL[0]['prompt']+'!', ORIGINAL[0]['prompt'].replace('방식이다','방식이오')]:
            with self.assertRaises(DuplicateQuizQuestionError):
                _check_new_questions([{'prompt':replacement}], ORIGINAL)
        with self.assertRaises(DuplicateQuizQuestionError):
            _check_new_questions([{'prompt':'원금 200원에 이자가 붙는 방식이다.'}], [{'prompt':'원금 100원에 이자가 붙는 방식이다.'}])

    async def test_different_user_or_concept_does_not_share_history(self):
        await self.create(AsyncMock(return_value=copy.deepcopy(ORIGINAL)), 'old')
        for user,concept in [('other-user','interest'),('novelty-user','other-concept')]:
            generator=AsyncMock(return_value=copy.deepcopy(ORIGINAL))
            created=await self.create(generator,'new-'+user+concept,user,concept)
            self.assertEqual(created.status,'completed')
            self.assertNotIn('previous_questions',generator.await_args.kwargs['learning_context'])

    async def test_same_session_still_returns_same_set_without_regeneration(self):
        old=await self.create(AsyncMock(return_value=copy.deepcopy(ORIGINAL)),'same')
        generator=AsyncMock(side_effect=AssertionError('must not regenerate'))
        duplicate=await self.create(generator,'same')
        self.assertEqual(old.id,duplicate.id)
        generator.assert_not_awaited()

    async def test_all_prior_sets_are_compared_not_only_latest(self):
        await self.create(AsyncMock(return_value=copy.deepcopy(ORIGINAL)),'first')
        await self.create(AsyncMock(return_value=alternative()),'second')
        generator=AsyncMock(return_value=copy.deepcopy(ORIGINAL))
        with patch('app.services.quiz_service.report_quiz_generation_failed',AsyncMock()), patch('app.services.quiz_service.logger.exception'):
            created=await self.create(generator,'third')
        self.assertEqual(created.status,'failed')
        self.assertEqual(len(generator.await_args_list[0].kwargs['learning_context']['previous_questions']),6)


if __name__=='__main__':
    unittest.main(verbosity=2)
