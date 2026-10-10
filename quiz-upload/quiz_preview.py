"""챗봇 학습 완료를 가정한 로컬 화면. 외부 AI·챗봇 호출 없음.

실제 퀴즈 생성·저장·채점·학습노트 서비스를 임시 DB에서 사용한다.
python -m uvicorn quiz_preview:app --host 127.0.0.1 --port 8010
"""

import os
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

# 기존 학습 기록과 분리된 프로세스 전용 미리보기 DB.
_preview_dir = tempfile.TemporaryDirectory(prefix="quiz-preview-")
os.environ["QUIZ_DATABASE_URL"] = "sqlite+aiosqlite:///" + (Path(_preview_dir.name) / "quiz.db").as_posix()

from app.api.v1.endpoints.quizzes import router
from app.api.deps import get_authenticated_user_id
from app.db import dispose_quiz_database, ensure_quiz_schema, session_scope
from app.errors import register_quiz_exception_handlers
from app.services.quiz_service import create_quiz_set

QUESTIONS = [
    dict(question_index=1, question_type="ox", prompt="분업은 생산 과정을 나누어 각자가 맡은 일을 수행하는 방식이오.",
         choices=[{"key": "O", "text": "맞아요"}, {"key": "X", "text": "아니에요"}],
         answer="O", explanation="분업은 업무를 나누고 각자가 맡은 부분을 수행하는 방식이오."),
    dict(question_index=2, question_type="ox", prompt="특화란 각자가 모든 일을 똑같이 나누어 맡는 것을 뜻하오.",
         choices=[{"key": "O", "text": "맞아요"}, {"key": "X", "text": "아니에요"}],
         answer="X", explanation="특화는 특정 업무에 집중하는 것이오. 모든 업무를 똑같이 맡는다는 뜻은 아니오."),
    dict(question_index=3, question_type="situation", prompt="학당 장터에서 빵을 팔려고 하오. 분업과 특화를 활용한 방법은 무엇이겠소?",
         choices=[{"key": "A", "text": "모두가 반죽부터 판매까지 전부 맡는다."},
                  {"key": "B", "text": "반죽·굽기·판매를 나누어 각자 잘하는 일에 집중한다."},
                  {"key": "C", "text": "한 사람만 모든 일을 하고 나머지는 기다린다."},
                  {"key": "D", "text": "담당 없이 매번 무작위로 일을 한다."}],
         answer="B", explanation="일을 나누는 것이 분업이고, 각자가 특정 업무에 집중하는 것이 특화이오."),
]


async def preview_generator(**kwargs):
    return QUESTIONS


@asynccontextmanager
async def lifespan(app):
    await ensure_quiz_schema()
    yield
    await dispose_quiz_database()
    _preview_dir.cleanup()


app = FastAPI(title="퀴즈 화면 미리보기", lifespan=lifespan)
app.include_router(router)
app.dependency_overrides[get_authenticated_user_id] = lambda: "preview-user"
register_quiz_exception_handlers(app)


@app.get("/", response_class=HTMLResponse)
def home(mode: str = ""):
    page = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>나의 경세학당 · 학습 완료</title>
<style>body{background:#f4f1ea;color:#1d1a16;font-family:Segoe UI,sans-serif;max-width:720px;margin:60px auto;padding:20px}article{background:white;border:1px solid #e4ddd2;border-radius:16px;padding:32px;margin:24px 0}small{color:#5c564e}p{line-height:1.8}button{background:#0b5f4a;color:white;border:0;border-radius:10px;padding:14px 24px;font:inherit;cursor:pointer}</style>
<small>나의 경세학당 · Stage 1</small><h1>배운 내용을 확인해 보시오.</h1>
<article><small>학습한 개념</small><h2>분업 / 특화</h2>
<p>분업은 일을 나누고, 특화는 특정 업무에 집중하는 것이오.<br>빵집에서 반죽·굽기·판매를 나누어 맡는 모습을 떠올려 보시오.</p>
<p>학습을 마쳤다면 세 문제를 풀어 보시오.<br>두 문제 이상 맞히면 통과하오.</p>
<form method="post" action="/preview/start"><button onclick="this.textContent='문제를 준비하는 중…'">퀴즈 풀기 →</button></form></article>
<small>챗봇 학습을 완료했다고 가정한 미리보기입니다. 문제는 예시이며 채점·저장은 실제 퀴즈 기능을 사용합니다. 학습 상태 반영은 아직 연결되지 않았습니다.</small></html>"""
    if mode == "relearn":
        page = page.replace("배운 내용을 확인해 보시오.", "분업 / 특화를 다시 배워 보시오.")
    elif mode == "next":
        page = page.replace("배운 내용을 확인해 보시오.", "다음 개념을 배울 준비가 되었소.")
        page = page.replace("<article><small>학습한 개념</small>", "<article><p>다음 개념 선택은 챗봇 연결 후 제공됩니다.</p><small>방금 학습한 개념</small>")
        page = page.replace("퀴즈 풀기 →", "예시 퀴즈 다시 풀기 →")
    return page


@app.post("/preview/start")
async def start():
    async with session_scope() as session:
        quiz = await create_quiz_set(
            session, user_id="preview-user", session_id=str(uuid.uuid4()),
            concept_id="sisa_1281", stage_id="stage1",
            learning_context={"concept": {"concept_id": "sisa_1281", "stage_id": "stage1", "definition": "분업은 일을 나누고 특화는 특정 업무에 집중하는 것이다."}},
            reference_chunk_ids=["sisa_1281"], generator=preview_generator,
        )
    return RedirectResponse(f"/quiz?quiz_set_id={quiz.id}", status_code=303)


@app.get("/quiz")
def quiz_page():
    return FileResponse(Path(__file__).parent / "quiz.html")
