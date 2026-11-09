"""Real AI sample collection and isolated timeout test for UT-QZ-16.

Uses local settings without printing credentials. All DB writes use temporary SQLite.
"""
import asyncio
import copy
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

ROOT=Path('C:\\Github\\AI-Financial-Knowledge-Platform\\quiz-upload')
sys.path.insert(0,str(ROOT))
sys.stdout.reconfigure(encoding='utf-8')
temp=tempfile.TemporaryDirectory(prefix='quiz-live-verification-')
os.environ['QUIZ_DATABASE_URL']='sqlite+aiosqlite:///'+(Path(temp.name)/'test.db').as_posix()
from openai import APITimeoutError
import httpx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from app.api.deps import get_authenticated_user_id
from app.api.v1.endpoints.quizzes import router
from app.db import ensure_quiz_schema, session_scope, dispose_quiz_database
from app.errors import register_quiz_exception_handlers
from app.models.quiz import QuizSet
from app.services.quiz_service import QuizService
from dotenv import load_dotenv
load_dotenv('C:\\Users\\korie\\Desktop\\나의 경세학당\\.env', override=False)
from database.settings import load_settings

OUT=Path('C:\\Github\\AI-Financial-Knowledge-Platform\\quiz-upload\\verification\\quiz-final-2026-11-09')
OUT.mkdir(parents=True,exist_ok=True)
result={'started_at':datetime.now(timezone.utc).isoformat(),'database':'temporary SQLite',
        'model':load_settings().openai_model,'samples':[],'timeout':{}}
contexts=[
 ('분업과 특화','분업은 생산 과정을 나누어 맡는 것이고, 특화는 특정 업무에 집중하는 것이다. 역할 분담은 숙련도를 높일 수 있지만 모든 상황에서 효율을 보장하지 않는다.'),
 ('기회비용','기회비용은 어떤 선택을 하면서 포기한 대안 중 가장 가치가 큰 대안의 가치이다. 포기한 모든 대안의 가치를 합산하지 않는다.'),
 ('희소성','희소성은 사람들의 욕구에 비해 이용할 수 있는 자원이 제한되어 있는 상태이다. 자원이 제한되어 있기 때문에 선택이 필요하다.'),
 ('고정비와 변동비','고정비는 일정한 범위에서 생산량에 따라 변하지 않는 비용이다. 변동비는 생산량이 달라짐에 따라 변하는 비용이다. 매장 임대료는 고정비의 예, 제품별 재료비는 변동비의 예이다.'),
 ('가계 예산','가계 예산은 예상 수입과 지출을 미리 계획하는 것이다. 지출이 수입보다 많으면 지출 조정 등의 검토가 필요하다. 예산 계획에는 실제 지출 확인도 도움이 된다.'),
 ('수요와 공급','다른 조건이 일정할 때 가격이 오르면 수요량은 감소하고 공급량은 증가하는 경향이 있다. 가격 자체 변화에 따른 수요량 변화와 다른 조건 변화로 인한 수요 곡선 이동은 구분한다.'),
 ('물가와 구매력','물가는 여러 상품과 서비스의 전반적인 가격 수준이다. 소득이 일정할 때 물가가 전반적으로 오르면 같은 돈으로 살 수 있는 양이 줄어 구매력이 낮아진다.')]

def save():
    (OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

async def main():
    await ensure_quiz_schema()
    if not load_settings().openai_api_key:
        raise RuntimeError('OPENAI_API_KEY not configured')
    app=FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_authenticated_user_id]=lambda:'qz16-user'
    register_quiz_exception_handlers(app)
    # External learning management is outside this test.
    with patch('app.services.quiz_service.report_quiz_result',AsyncMock()), patch('app.services.quiz_service.report_quiz_generation_failed',AsyncMock()):
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            for i,(term,definition) in enumerate(contexts,1):
                row={'trial':i,'term':term,'context':definition}
                started=time.perf_counter()
                # Suppress SDK exception logs: persist only a safe summary, never credentials.
                with patch('app.services.quiz_service.logger.exception') as errors:
                    async with session_scope() as session:
                        quiz=await QuizService().create_quiz_set(session,user_id='qz16-user',session_id=f'live-{i}',
                            concept_id=f'verification-{i}',stage_id='stage1',learning_context={'concept':{'term':term},'definition':definition})
                        row['generation_seconds']=round(time.perf_counter()-started,3)
                        row['status']=quiz.status
                        stored=await session.get(QuizSet,quiz.id)
                        row['questions']=copy.deepcopy(stored.questions)
                if quiz.status!='completed':
                    row['failure']='AI generation failed; no valid sample collected'
                    # Extract only safe provider diagnostics from the caught exception.
                    if errors.call_args:
                        row['failure_logged']=True
                    result['samples'].append(row)
                    save()
                    print(f'Trial {i}: failed; stopping additional paid calls',flush=True)
                    break
                row['structure_ok']=[q['question_type'] for q in row['questions']]==['ox','ox','situation'] and len(row['questions'][2]['choices'])==4
                if i<=3:
                    payload={'submitted_answers':[{'question_index':q['question_index'],'answer':q['answer']} for q in row['questions']],
                             'idempotency_key':f'grade-{i}'}
                    started=time.perf_counter()
                    response=await client.post(f'/api/v1/quiz-sets/{quiz.id}/submit',json=payload)
                    row['grading_seconds']=round(time.perf_counter()-started,4)
                    row['grading_status']=response.status_code
                    row['grading_ok']=response.status_code==200 and response.json().get('correct_count')==3
                result['samples'].append(row)
                save()
                print(f"Trial {i}: {term}; generation={row['generation_seconds']}s; grade={row.get('grading_seconds','not measured')}; structure={row['structure_ok']}",flush=True)
            # Exercise the real OpenAI wrapper and service failure path, substituting only the provider client.
            mock_client=AsyncMock()
            mock_client.beta.chat.completions.parse.side_effect=APITimeoutError(request=httpx.Request('POST','https://api.openai.com/v1/chat/completions'))
            manager=AsyncMock()
            manager.__aenter__.return_value=mock_client
            with patch('app.services.quiz_service.AsyncOpenAI',return_value=manager) as factory, patch('app.services.quiz_service.logger.exception'):
                async with session_scope() as session:
                    failed=await QuizService().create_quiz_set(session,user_id='qz16-user',session_id='timeout-mock',concept_id='timeout-test',stage_id='stage1',learning_context='test')
            response=await client.get(f'/api/v1/quiz-sets/{failed.id}')
            async with session_scope() as session:
                saved=await session.get(QuizSet,failed.id)
                result['timeout']={'injected_error':'APITimeoutError','sdk_timeout':factory.call_args.kwargs['timeout'],
                    'sdk_max_retries':factory.call_args.kwargs['max_retries'],'returned_status':failed.status,
                    'stored_status':saved.status,'stored_questions':saved.questions,'get_status':response.status_code,
                    'get_body_status':response.json().get('status'),'passed':failed.status==saved.status=='failed' and saved.questions==[] and response.status_code==200 and response.json()['status']=='failed'}
            result['timeout']['note']='API exposes failed status. Browser error-message rendering was not inspected.'
            save()
            print('Timeout simulation:',result['timeout']['passed'],flush=True)
    await dispose_quiz_database()

try:
    asyncio.run(main())
finally:
    save()
    temp.cleanup()
