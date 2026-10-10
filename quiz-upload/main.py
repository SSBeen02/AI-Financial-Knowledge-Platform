import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.v1.endpoints.quizzes import router as quizzes_router
from app.db import dispose_quiz_database, ensure_quiz_schema
from app.errors import register_quiz_exception_handlers

logger = logging.getLogger("quiz")
QUIZ_PAGE = Path(__file__).resolve().parent / "quiz.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    await ensure_quiz_schema()
    logger.info("퀴즈 모듈 준비")
    try:
        yield
    finally:
        await dispose_quiz_database()


app = FastAPI(
    title="경세학당 퀴즈 API",
    version="0.1.0",
    description=(
        "개념 확인 퀴즈를 조회하고 제출합니다. "
        "공통 인증 모듈 연동 전에는 서버가 user_id를 test-user-123으로 기록합니다."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(quizzes_router)
register_quiz_exception_handlers(app)


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(QUIZ_PAGE)


@app.get("/quiz", include_in_schema=False)
def quiz_page() -> FileResponse:
    return FileResponse(QUIZ_PAGE)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
