"""Learning notes with the latest immutable-first-submission quiz behavior."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.api.deps import get_authenticated_user_id
from app.api.v1.endpoints.quizzes import router as quiz_router
from app.db import Base, get_session
from app.errors import register_quiz_exception_handlers
from app.models.quiz import QuizSet, QuizSubmission, QuizReview
from app.services.learning_notes import router as notes_router
from app.services.quiz_service import QuizService

class LearningNotesQuizCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_result_relearning_rounds_and_reviews_remain_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine=create_async_engine('sqlite+aiosqlite:///'+(Path(tmp)/'combined.db').as_posix())
            factory=async_sessionmaker(engine,expire_on_commit=False)
            try:
                async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
                app=FastAPI();app.include_router(quiz_router);app.include_router(notes_router)
                register_quiz_exception_handlers(app)
                async def session():
                    async with factory() as db:yield db
                app.dependency_overrides[get_session]=session
                app.dependency_overrides[get_authenticated_user_id]=lambda:'owner'
                service=QuizService()
                quiz_ids=[]
                for name in ['initial','relearning']:
                    async with factory() as db:
                        q=await service.create_quiz_set(db,user_id='owner',session_id=name,
                            concept_id='sisa_1552',stage_id='stage5',learning_context='검증용 학습 맥락')
                        quiz_ids.append(q.id)
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    ids=[]
                    for attempt,qid in enumerate(quiz_ids):
                        async with factory() as db:stored=copy.deepcopy((await db.get(QuizSet,qid)).questions)
                        answers=[dict(question_index=q['question_index'],answer=(q['answer'] if attempt==1 or i==0 else next(c['key'] for c in q['choices'] if c['key']!=q['answer']))) for i,q in enumerate(stored)]
                        response=await client.post(f'/api/v1/quiz-sets/{qid}/submit',json={
                            'submitted_answers':answers,'idempotency_key':f'first-{attempt}'})
                        self.assertEqual(response.status_code,200,response.text)
                        ids.append(response.json()['submission_id'])
                        if attempt==0:
                            original_response=response.json()
                            replay=await client.post(f'/api/v1/quiz-sets/{qid}/submit',json={
                                'submitted_answers':[dict(question_index=q['question_index'],answer=q['answer']) for q in stored],
                                'idempotency_key':'different-key-for-same-set'})
                            self.assertEqual(replay.status_code,200,replay.text)
                            self.assertEqual(replay.json()['submission_id'],ids[0])
                            self.assertEqual(replay.json()['correct_count'],original_response['correct_count'])
                    page=(await client.get('/api/v1/learning-notes/concepts?stage_id=stage5')).json()
                    self.assertEqual(page['total'],1)
                    group=page['items'][0]
                    self.assertEqual(group['total_attempts'],2)
                    self.assertEqual({q['attempt_number'] for q in group['questions']},{1,2})
                    self.assertEqual(len(group['questions']),6)
                    self.assertEqual({q['submission_id'] for q in group['questions']},set(ids))
                    original_question=next(q for q in group['questions'] if q['submission_id']==ids[0] and q['question_index']==2)
                    before=copy.deepcopy(group['questions'])
                    with patch('app.services.quiz_service.report_quiz_result',new_callable=AsyncMock) as notify:
                        for i in range(2):
                            r=await client.post(f'/api/v1/learning-notes/submissions/{ids[0]}/questions/2/reviews',json={
                                'answer':original_question['answer'],'idempotency_key':f'review-{i}'})
                            self.assertEqual(r.status_code,200,r.text)
                        notify.assert_not_awaited()
                    after=(await client.get('/api/v1/learning-notes/concepts?stage_id=stage5')).json()['items'][0]
                    for q in after['questions']:
                        previous=next(x for x in before if x['submission_id']==q['submission_id'] and x['question_index']==q['question_index'])
                        for field in ('submitted_answer','is_correct','is_passed','attempt_number'):
                            self.assertEqual(q[field],previous[field])
                    target=next(q for q in after['questions'] if q['submission_id']==ids[0] and q['question_index']==2)
                    self.assertEqual(len(target['reviews']),2)
                    wrong=(await client.get('/api/v1/learning-notes/concepts?stage_id=stage5&filter=wrong')).json()['items'][0]
                    self.assertTrue(all(q['submission_id']==ids[0] and q['attempt_number']==1 and q['is_correct'] is False for q in wrong['questions']))
                    async with factory() as db:
                        self.assertEqual(await db.scalar(select(func.count()).select_from(QuizSubmission)),2)
                        self.assertEqual(await db.scalar(select(func.count()).select_from(QuizReview)),2)
            finally:await engine.dispose()
