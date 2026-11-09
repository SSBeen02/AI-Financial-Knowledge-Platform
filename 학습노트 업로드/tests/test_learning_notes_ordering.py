"""API ordering over more than one concept page, with owner/stage isolation."""
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.api.deps import get_authenticated_user_id
from app.db import Base, get_session
from app.errors import register_quiz_exception_handlers
from app.models.quiz import QuizSet, QuizSubmission
from app.services.learning_notes import router
from app.timeutil import utc_now


class LearningNotesOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_before_pagination_and_default_compatibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=create_async_engine('sqlite+aiosqlite:///'+(Path(tmp)/'notes.db').as_posix())
            factory=async_sessionmaker(engine,expire_on_commit=False)
            try:
                async with engine.begin() as db: await db.run_sync(Base.metadata.create_all)
                now=utc_now()
                async with factory() as db:
                    for i in range(23):
                        qid,sid=str(uuid.uuid4()),str(uuid.uuid4())
                        user='other' if i==21 else 'owner'
                        stage='stage2' if i==22 else 'stage1'
                        q=QuizSet(id=qid,user_id=user,concept_id=f'c{i:02}',stage_id=stage,
                            learning_session_id=str(uuid.uuid4()),status='completed',created_at=now,
                            questions=[dict(question_index=1,question_type='ox',prompt='예시',
                                choices=[dict(key='O',text='O'),dict(key='X',text='X')],
                                answer='O',explanation='예시이오.',term=f'가{i:02}')])
                        db.add(q);await db.flush()
                        db.add(QuizSubmission(id=sid,quiz_set_id=qid,user_id=user,idempotency_key=sid,
                            submitted_answers=[dict(question_index=1,answer='X')],is_correct_list=[False],
                            correct_count=0,is_passed=False,created_at=now+timedelta(seconds=i)))
                    await db.commit()
                app=FastAPI();app.include_router(router);register_quiz_exception_handlers(app)
                async def session():
                    async with factory() as db: yield db
                app.dependency_overrides[get_session]=session
                app.dependency_overrides[get_authenticated_user_id]=lambda:'owner'
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    for sort,expected in [('alphabetical',[f'c{i:02}' for i in range(21)]),
                                          ('latest',[f'c{i:02}' for i in range(20,-1,-1)])]:
                        actual=[]
                        for page in (1,2):
                            r=await client.get('/api/v1/learning-notes/concepts',params={
                                'sort':sort,'filter':'wrong','stage_id':'stage1','page':page})
                            self.assertEqual(r.status_code,200,r.text)
                            self.assertEqual(r.json()['total'],21)
                            actual.extend(g['concept_id'] for g in r.json()['items'])
                        self.assertEqual(actual,expected)
                    default=await client.get('/api/v1/learning-notes/concepts?stage_id=stage1')
                    self.assertEqual(default.json()['items'][0]['concept_id'],'c00')
                    invalid=await client.get('/api/v1/learning-notes/concepts?sort=invalid')
                    self.assertEqual(invalid.status_code,422)
            finally: await engine.dispose()
