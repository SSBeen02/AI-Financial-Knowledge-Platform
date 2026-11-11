"""Original quiz requirements: format recovery, time bounds and immutable first result."""
import asyncio
import ast
import copy
import importlib.util
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.db import Base
from app.models.quiz import QuizSet, QuizSubmission
from app.services.quiz_service import QuizService, QuizFormatError, normalize_questions

ROOT=Path(__file__).resolve().parents[1]
tree=ast.parse((ROOT/'tests/test_quizzes.py').read_text(encoding='utf-8-sig'))
SAMPLE=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
    and any(isinstance(t,ast.Name) and t.id=='SAMPLE_QUESTIONS' for t in n.targets))

class OriginalQuizRequirementsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='quiz-requirements-')
        self.engine=create_async_engine('sqlite+aiosqlite:///'+(Path(self.temp.name)/'test.db').as_posix())
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory=async_sessionmaker(self.engine,expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.temp.cleanup()

    async def create(self,generator,session_id='first',stage='stage1'):
        async with self.factory() as session:
            return await QuizService(generator).create_quiz_set(session,user_id='owner',session_id=session_id,
                concept_id='concept',stage_id=stage,learning_context='학습 맥락')

    async def test_format_failure_recovers_on_third_attempt(self):
        generator=AsyncMock(side_effect=[[],[],copy.deepcopy(SAMPLE)])
        created=await self.create(generator)
        self.assertEqual(created.status,'completed')
        self.assertEqual(generator.await_count,3)

    async def test_exhausted_format_failures_store_empty_failed_and_notify_once(self):
        generator=AsyncMock(return_value=[])
        notify=AsyncMock()
        with patch('app.services.quiz_service.report_quiz_generation_failed',notify):
            created=await self.create(generator)
        self.assertEqual(generator.await_count,3)
        self.assertEqual(created.status,'failed')
        notify.assert_awaited_once_with('first',user_id='owner')
        async with self.factory() as session:
            self.assertEqual((await session.get(QuizSet,created.id)).questions,[])

    async def test_foreign_language_is_rejected_and_regenerated(self):
        bad_prompt = copy.deepcopy(SAMPLE)
        bad_prompt[0]["prompt"] = "GDP의 의미는 무엇이오?"
        bad_choice = copy.deepcopy(SAMPLE)
        bad_choice[2]["choices"][0]["text"] = "価格"
        bad_explanation = copy.deepcopy(SAMPLE)
        bad_explanation[0]["explanation"] = "이 문항은 English 설명이오."
        for questions in (bad_prompt, bad_choice, bad_explanation):
            with self.assertRaisesRegex(ValueError, "한글|한국어"):
                normalize_questions(questions)

        generator = AsyncMock(side_effect=[bad_prompt, bad_choice, copy.deepcopy(SAMPLE)])
        result = await self.create(generator)
        self.assertEqual(result.status, "completed")
        self.assertEqual(generator.await_count, 3)

    async def test_transport_error_not_retried_by_format_loop(self):
        generator=AsyncMock(side_effect=RuntimeError('transport failure'))
        with patch('app.services.quiz_service.report_quiz_generation_failed',AsyncMock()):
            created=await self.create(generator)
        self.assertEqual(created.status,'failed')
        self.assertEqual(generator.await_count,1)

    async def test_ai_schema_parse_failure_is_regenerated(self):
        generator=AsyncMock(side_effect=[QuizFormatError('bad schema'),copy.deepcopy(SAMPLE)])
        created=await self.create(generator)
        self.assertEqual(created.status,'completed')
        self.assertEqual(generator.await_count,2)

    async def test_required_null_field_is_rejected(self):
        sample=copy.deepcopy(SAMPLE)
        sample[0]['explanation']=None
        with self.assertRaises(ValueError): normalize_questions(sample)

    async def test_generation_deadline_cancels_work_before_failed_save(self):
        cancelled=asyncio.Event()
        async def slow(**kwargs):
            try: await asyncio.sleep(10)
            finally: cancelled.set()
        with patch('app.services.quiz_service.GENERATION_TIMEOUT_SECONDS',0.02),patch('app.services.quiz_service.report_quiz_generation_failed',AsyncMock()) as notify:
            created=await self.create(slow)
        self.assertEqual(created.status,'failed')
        self.assertTrue(cancelled.is_set())
        notify.assert_awaited_once()
        async with self.factory() as session:
            row=await session.get(QuizSet,created.id)
            self.assertEqual((row.status,row.questions),('failed',[]))

    async def test_different_key_cannot_replace_first_failed_result(self):
        created=await self.create(AsyncMock(return_value=copy.deepcopy(SAMPLE)))
        async with self.factory() as session:
            service=QuizService()
            with patch('app.services.quiz_service.report_quiz_result',AsyncMock()) as notify:
                first=await service.submit_quiz_answers(session,user_id='owner',quiz_set_id=created.id,
                    submitted_answers=[dict(question_index=i,answer=a) for i,a in enumerate(['X','X','A'],1)],idempotency_key='first-key')
                second=await service.submit_quiz_answers(session,user_id='owner',quiz_set_id=created.id,
                    submitted_answers=[dict(question_index=i,answer=a) for i,a in enumerate(['O','O','B'],1)],idempotency_key='other-key')
            self.assertFalse(first.is_passed)
            self.assertEqual(first.model_dump(),second.model_dump())
            self.assertEqual(await session.scalar(select(func.count()).select_from(QuizSubmission)),1)
            self.assertEqual({c.kwargs['submission_id'] for c in notify.await_args_list},{first.submission_id})

    async def test_stage5_invalid_bank_never_regenerates_with_ai(self):
        generator=AsyncMock(side_effect=AssertionError('AI forbidden'))
        with patch('app.services.stage5_bank.fixed_questions',return_value=[]),patch('app.services.quiz_service.report_quiz_generation_failed',AsyncMock()):
            created=await self.create(generator,stage='stage5')
        self.assertEqual(created.status,'failed')
        generator.assert_not_awaited()

    def test_exact_four_choices_and_distinct_labels(self):
        for kind in ('three','five','duplicate-label','duplicate-key','invalid-key'):
            with self.subTest(kind=kind):
                sample=copy.deepcopy(SAMPLE)
                choices=sample[2]['choices']
                if kind=='three': choices.pop()
                if kind=='five': choices.append(dict(key='E',text='다섯 번째 보기'))
                if kind=='duplicate-label': choices[1]['text']=choices[0]['text']
                if kind=='duplicate-key': choices[1]['key']='A'
                if kind=='invalid-key': choices[3]['key']='E'
                with self.assertRaises(ValueError): normalize_questions(sample)
        self.assertEqual(len(normalize_questions(copy.deepcopy(SAMPLE))[2]['choices']),4)

class SQLiteMigrationTests(unittest.TestCase):
    def test_duplicate_migration_aborts_without_deleting_records(self):
        spec=importlib.util.spec_from_file_location('first_submission_migration',ROOT/'scripts/migrate_first_submission_sqlite.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'old.db'
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute('create table quiz_submissions(quiz_set_id text)')
                conn.executemany('insert into quiz_submissions values (?)',[('same',),('same',)])
            with self.assertRaises(RuntimeError): module.migrate(db,apply=True,backup=Path(temp)/'backup.db')
            with closing(sqlite3.connect(db)) as conn, conn:
                self.assertEqual(conn.execute('select count(*) from quiz_submissions').fetchone()[0],2)

    def test_migration_backup_and_unique_index(self):
        spec=importlib.util.spec_from_file_location('first_submission_migration',ROOT/'scripts/migrate_first_submission_sqlite.py')
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'old.db'; backup=Path(temp)/'backup.db'
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute('create table quiz_submissions(quiz_set_id text)')
                conn.execute("insert into quiz_submissions values ('one')")
            module.migrate(db,apply=True,backup=backup)
            with closing(sqlite3.connect(db)) as conn, conn:
                with self.assertRaises(sqlite3.IntegrityError): conn.execute("insert into quiz_submissions values ('one')")
            with closing(sqlite3.connect(backup)) as conn:
                self.assertEqual(conn.execute('select count(*) from quiz_submissions').fetchone()[0],1)
