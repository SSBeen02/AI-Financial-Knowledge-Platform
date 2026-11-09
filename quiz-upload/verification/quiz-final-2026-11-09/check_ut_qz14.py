import ast
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import AsyncMock, patch

ROOT=Path('C:\\Github\\AI-Financial-Knowledge-Platform\\quiz-upload')
sys.path.insert(0,str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
temp=tempfile.TemporaryDirectory(prefix='quiz-callback-check-')
os.environ['QUIZ_DATABASE_URL']='sqlite+aiosqlite:///'+(Path(temp.name)/'test.db').as_posix()

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select, func
from app.api.deps import get_authenticated_user_id
from app.api.v1.endpoints.quizzes import router
from app.db import ensure_quiz_schema, session_scope, dispose_quiz_database
from app.errors import register_quiz_exception_handlers
from app.models.quiz import QuizSet, QuizSubmission
from app.services.quiz_service import QuizService

tree=ast.parse((ROOT/'tests/test_quizzes.py').read_text(encoding='utf-8-sig'))
sample=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SAMPLE_QUESTIONS' for t in n.targets))
async def good(**kwargs): return copy.deepcopy(sample)
async def bad(**kwargs): raise RuntimeError('TEST: simulated generator failure')
app=FastAPI()
app.include_router(router)
app.dependency_overrides[get_authenticated_user_id]=lambda:'qz14-user'
register_quiz_exception_handlers(app)

async def main():
    await ensure_quiz_schema()
    rows=[]
    def record(name,condition,**detail):
        rows.append(dict(case=name,pass_=bool(condition),**detail))
        print(('PASS' if condition else 'FAIL'),name,detail,flush=True)
    async with session_scope() as session:
        quiz=await QuizService(good).create_quiz_set(session,user_id='qz14-user',session_id='pass-session',concept_id='test',stage_id='stage1',learning_context='test')
    payload={'submitted_answers':[{'question_index':i,'answer':a} for i,a in enumerate(['O','O','B'],1)],'idempotency_key':'qz14-pass'}
    notify=AsyncMock(side_effect=RuntimeError('TEST: result callback failure'))
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        with patch('app.services.quiz_service.report_quiz_result',notify):
            with patch('app.services.quiz_service.logger.exception') as logged:
                response=await client.post(f'/api/v1/quiz-sets/{quiz.id}/submit',json=payload)
                body=response.json()
                record('결과 보고 예외 후에도 200·정상 채점',response.status_code==200 and body.get('correct_count')==3 and body.get('is_passed') is True,status=response.status_code)
                record('결과 보고 호출·예외 로그 확인',notify.await_count==1 and logged.called)
                again=await client.post(f'/api/v1/quiz-sets/{quiz.id}/submit',json=payload)
                record('재전송에도 저장된 결과 반환',again.status_code==200 and again.json().get('submission_id')==body.get('submission_id'))
        async with session_scope() as session:
            saved=await session.get(QuizSubmission,body.get('submission_id'))
            count=await session.scalar(select(func.count()).select_from(QuizSubmission))
            record('새 DB 세션에서 채점 기록 유지·중복 없음',saved is not None and saved.correct_count==3 and saved.is_passed is True and count==1,count=count)
        failed_notify=AsyncMock(side_effect=RuntimeError('TEST: failure callback failure'))
        with patch('app.services.quiz_service.report_quiz_generation_failed',failed_notify):
            with patch('app.services.quiz_service.logger.exception') as logged:
                async with session_scope() as session:
                    failed=await QuizService(bad).create_quiz_set(session,user_id='qz14-user',session_id='failed-session',concept_id='test',stage_id='stage1',learning_context='test')
                record('생성 실패 보고 예외 후에도 failed 반환',failed.status=='failed')
                record('생성 실패 보고 호출·예외 로그 확인',failed_notify.await_count==1 and logged.call_count>=2)
        async with session_scope() as session:
            stored=await session.get(QuizSet,failed.id)
            count=await session.scalar(select(func.count()).select_from(QuizSubmission))
            record('새 DB 세션에서 failed 저장 유지',stored is not None and stored.status=='failed' and stored.questions==[])
            record('생성 실패 시 채점 기록 추가 없음',count==1)
        response=await client.get(f'/api/v1/quiz-sets/{failed.id}')
        record('API 재조회에서도 failed·빈 문항 반환',response.status_code==200 and response.json()['status']=='failed' and response.json()['questions']==[])
    (Path('C:\\Github\\AI-Financial-Knowledge-Platform\\quiz-upload\\verification\\quiz-final-2026-11-09\\ut-qz14-results.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RESULT',sum(r['pass_'] for r in rows),'/',len(rows),flush=True)
    await dispose_quiz_database()
    assert all(r['pass_'] for r in rows)

try:
    asyncio.run(main())
finally:
    temp.cleanup()
