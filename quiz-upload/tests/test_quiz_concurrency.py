"""UT-QZ-15: real UNIQUE collisions using independent SQLite sessions.

Only timing is controlled; database errors and recovery use production code.
Run this file directly to also write doc_qa/ut-qz15-results.json.
"""
import ast
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.db import dispose_quiz_database, ensure_quiz_schema, get_engine
from app.models.quiz import QuizSet, QuizSubmission
from app.services.quiz_service import QuizService

RESULTS = []
tree = ast.parse((ROOT / 'tests/test_quizzes.py').read_text(encoding='utf-8-sig'))
SAMPLE = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'SAMPLE_QUESTIONS' for t in n.targets))


class RaceSession(AsyncSession):
    async def commit(self):
        state = self.info.get('race')
        target = self.info.get('target')
        if state and not self.info.get('synchronized') and any(isinstance(row, target) for row in self.new):
            self.info['synchronized'] = True
            state['arrivals'] += 1
            if state['arrivals'] == 2:
                state['ready'].set()
            await asyncio.wait_for(state['ready'].wait(), timeout=10)
        try:
            return await super().commit()
        except IntegrityError as exc:
            if state:
                state['integrity_errors'].append(str(exc.orig))
                self.info['collision'] = True
            raise

    async def rollback(self):
        value = await super().rollback()
        if self.info.get('collision'):
            self.info['recovery_rollback'] = True
            self.info['race']['rollbacks'] += 1
        return value

    async def execute(self, *args, **kwargs):
        value = await super().execute(*args, **kwargs)
        if self.info.get('recovery_rollback'):
            self.info['race']['queries_after_rollback'] += 1
        return value


class QuizConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await dispose_quiz_database()
        self.old_url = os.environ.get('QUIZ_DATABASE_URL')
        self.temp = tempfile.TemporaryDirectory(prefix='quiz-race-')
        os.environ['QUIZ_DATABASE_URL'] = 'sqlite+aiosqlite:///' + (Path(self.temp.name) / 'race.db').as_posix()
        await ensure_quiz_schema()
        self.factory = async_sessionmaker(get_engine(), class_=RaceSession, expire_on_commit=False)

    async def asyncTearDown(self):
        await dispose_quiz_database()
        if self.old_url is None:
            os.environ.pop('QUIZ_DATABASE_URL', None)
        else:
            os.environ['QUIZ_DATABASE_URL'] = self.old_url
        self.temp.cleanup()

    def state(self):
        return dict(ready=asyncio.Event(), arrivals=0, integrity_errors=[], rollbacks=0, queries_after_rollback=0)

    def verify_collision(self, state, table):
        self.assertEqual(state['arrivals'], 2)
        self.assertEqual(len(state['integrity_errors']), 1)
        self.assertIn('UNIQUE constraint failed', state['integrity_errors'][0])
        self.assertIn(table, state['integrity_errors'][0])
        self.assertEqual(state['rollbacks'], 1)
        self.assertGreaterEqual(state['queries_after_rollback'], 1)

    async def test_concurrent_generation_unique_collision_recovers(self):
        state = self.state()
        generator = AsyncMock(return_value=copy.deepcopy(SAMPLE))
        service = QuizService(generator)

        async def request():
            async with self.factory(info={'race': state, 'target': QuizSet}) as session:
                return await service.create_quiz_set(session, user_id='race-user', session_id='same-session',
                    concept_id='test-concept', stage_id='stage1', learning_context='test')

        first, second = await asyncio.wait_for(asyncio.gather(request(), request()), timeout=20)
        self.verify_collision(state, 'quiz_sets')
        self.assertEqual(first.id, second.id)
        self.assertEqual(generator.await_count, 1)
        async with self.factory() as session:
            count = await session.scalar(select(func.count()).select_from(QuizSet))
            saved = await session.get(QuizSet, first.id)
            self.assertEqual(count, 1)
            self.assertEqual(saved.status, 'completed')
            self.assertEqual(len(saved.questions), 3)
        RESULTS.append(dict(case='동시 생성', database='SQLite', request_count=2,
            unique_error=state['integrity_errors'][0], rollback_count=state['rollbacks'],
            queries_after_rollback=state['queries_after_rollback'], same_quiz_id=first.id==second.id,
            stored_sets=count, generator_calls=generator.await_count, passed=True))

    async def test_concurrent_submission_unique_collision_recovers(self):
        service = QuizService(AsyncMock(return_value=copy.deepcopy(SAMPLE)))
        async with self.factory() as session:
            quiz = await service.create_quiz_set(session, user_id='race-user', session_id='submit-session',
                concept_id='test-concept', stage_id='stage1', learning_context='test')
        state = self.state()
        answers = [dict(question_index=i, answer=a) for i, a in enumerate(['O','O','B'],1)]

        async def request():
            async with self.factory(info={'race': state, 'target': QuizSubmission}) as session:
                return await service.submit_quiz_answers(session, user_id='race-user', quiz_set_id=quiz.id,
                    submitted_answers=copy.deepcopy(answers), idempotency_key='same-key')

        notify = AsyncMock()
        with patch('app.services.quiz_service.report_quiz_result', notify):
            first, second = await asyncio.wait_for(asyncio.gather(request(), request()), timeout=20)
        self.verify_collision(state, 'quiz_submissions')
        self.assertEqual(first.submission_id, second.submission_id)
        self.assertEqual(first.model_dump(), second.model_dump())
        self.assertEqual(first.correct_count, 3)
        self.assertTrue(first.is_passed)
        self.assertEqual(notify.await_count, 2)
        self.assertEqual({call.kwargs['submission_id'] for call in notify.await_args_list}, {first.submission_id})
        async with self.factory() as session:
            count = await session.scalar(select(func.count()).select_from(QuizSubmission))
            saved = await session.get(QuizSubmission, first.submission_id)
            self.assertEqual(count, 1)
            self.assertEqual(saved.correct_count, 3)
            self.assertTrue(saved.is_passed)
        RESULTS.append(dict(case='동시 제출', database='SQLite', request_count=2,
            unique_error=state['integrity_errors'][0], rollback_count=state['rollbacks'],
            queries_after_rollback=state['queries_after_rollback'], same_submission_id=True,
            same_result=True, stored_submissions=count, passed=True))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(QuizConcurrencyTest))
    output = {'all_passed': result.wasSuccessful(), 'tests_run': result.testsRun, 'cases': RESULTS}
    result_path = ROOT/'verification/ut-qz15-results.json'
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(output,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
