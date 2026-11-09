import ast
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path('C:\\Github\\AI-Financial-Knowledge-Platform\\quiz-upload')
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
print('UT-QZ-10: isolated SQLite/API checks starting', flush=True)
temp = tempfile.TemporaryDirectory(prefix='quiz-submit-check-')
os.environ['QUIZ_DATABASE_URL'] = 'sqlite+aiosqlite:///' + (Path(temp.name) / 'test.db').as_posix()

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from app.api.deps import get_authenticated_user_id
from app.api.v1.endpoints.quizzes import router
from app.db import ensure_quiz_schema, session_scope, dispose_quiz_database
from app.errors import register_quiz_exception_handlers
from app.models.quiz import QuizSet, QuizSubmission
from app.timeutil import utc_now

tree = ast.parse((ROOT / 'tests/test_quizzes.py').read_text(encoding='utf-8-sig'))
sample = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SAMPLE_QUESTIONS' for t in n.targets))
app = FastAPI()
app.include_router(router)
app.dependency_overrides[get_authenticated_user_id] = lambda: 'qz10-user'
register_quiz_exception_handlers(app)

async def main():
    await ensure_quiz_schema()
    ids = {}
    async with session_scope() as session:
        for state in ['completed', 'failed', 'processing', 'pending']:
            ids[state] = str(uuid.uuid4())
            session.add(QuizSet(id=ids[state], user_id='qz10-user', learning_session_id='test-'+state,
                                concept_id='test-concept', stage_id='stage1', status=state,
                                questions=copy.deepcopy(sample) if state == 'completed' else [], created_at=utc_now()))
        await session.commit()
    base = {'submitted_answers': [{'question_index': i, 'answer': a} for i,a in enumerate(['O','O','B'], 1)], 'idempotency_key': 'qz10'}
    cases = [(state+' 세트 제출', ids[state], copy.deepcopy(base), 409, 'QUIZ_NOT_READY') for state in ['failed','processing','pending']]
    def change(name, mutate):
        payload = copy.deepcopy(base)
        mutate(payload)
        cases.append((name, ids['completed'], payload, 422, None))
    change('허용되지 않은 user_id', lambda p: p.update(user_id='other-user'))
    change('답안 목록 누락', lambda p: p.pop('submitted_answers'))
    change('답안 2개', lambda p: p['submitted_answers'].pop())
    change('답안 4개', lambda p: p['submitted_answers'].append({'question_index':1,'answer':'O'}))
    change('문항 번호 중복', lambda p: p['submitted_answers'][1].update(question_index=1))
    change('문항 번호 0', lambda p: p['submitted_answers'][0].update(question_index=0))
    change('문항 번호 4', lambda p: p['submitted_answers'][2].update(question_index=4))
    change('answer 필드 누락', lambda p: p['submitted_answers'][0].pop('answer'))
    change('빈 답안', lambda p: p['submitted_answers'][0].update(answer=''))
    change('멱등 키 누락', lambda p: p.pop('idempotency_key'))
    change('빈 멱등 키', lambda p: p.update(idempotency_key=''))
    change('답안 안의 허용되지 않은 필드', lambda p: p['submitted_answers'][0].update(user_id='other-user'))
    rows=[]
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        for name, quiz_id, payload, expected_status, expected_code in cases:
            response = await client.post(f'/api/v1/quiz-sets/{quiz_id}/submit', json=payload)
            body=response.json()
            ok=response.status_code == expected_status and (expected_code is None or body.get('code')==expected_code)
            rows.append({'case':name,'status':response.status_code,'code':body.get('code'),'pass':ok})
            print(('PASS' if ok else 'FAIL'), name, response.status_code, body.get('code'), flush=True)
        async with session_scope() as session:
            count=await session.scalar(select(func.count()).select_from(QuizSubmission))
        rows.append({'case':'거부한 요청의 제출 저장 0건','count':count,'pass':count==0})
        print('Rejected submission rows:', count, flush=True)
        response=await client.post(f"/api/v1/quiz-sets/{ids['completed']}/submit",json=base)
        body=response.json()
        ok=response.status_code==200 and body.get('correct_count')==3
        rows.append({'case':'정상 제출 대조군','status':response.status_code,'correct_count':body.get('correct_count'),'pass':ok})
        print('Normal control:',response.status_code,body.get('correct_count'),flush=True)
    (Path('C:\\Github\\AI-Financial-Knowledge-Platform\\quiz-upload\\verification\\quiz-final-2026-11-09\\ut-qz10-results.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print('RESULT',sum(row['pass'] for row in rows),'/',len(rows),flush=True)
    await dispose_quiz_database()
    if not all(row['pass'] for row in rows):
        raise SystemExit(1)

try:
    asyncio.run(main())
finally:
    temp.cleanup()
