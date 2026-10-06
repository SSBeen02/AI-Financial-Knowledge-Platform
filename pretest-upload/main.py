import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from database.settings import load_settings
from database.repository import get_repository
from routers.diagnostics import router as diagnostics_router
from routers.errors import register_pretest_exception_handlers
from routers.reports import router as reports_router
from services.llm_report import describe_llm_mode
from services.question_bank import count_by_domain, load_questions

logger = logging.getLogger("diagnostics")
INDEX_FILE = Path(__file__).resolve().parent / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    questions = load_questions()
    repository = get_repository()
    logger.info(
        "사전테스트 문항 %s개 %s, 저장소 %s, LLM %s",
        len(questions),
        count_by_domain(questions),
        repository.backend_name,
        describe_llm_mode(),
    )
    yield


app = FastAPI(
    title="경세학당 사전테스트 API",
    version="0.1.0",
    description=(
        "사전테스트를 시작하고, 제출된 답안을 채점해 영역별 취약점 리포트를 만듭니다. "
        "DEV_MODE=true일 때만 임시 사용자로 실행하며, 통합 서버에서는 공통 인증을 연결합니다."
    ),
    lifespan=lifespan,
)

load_settings()  # CORS 환경변수도 .env에서 읽는다.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(diagnostics_router)
app.include_router(reports_router)
register_pretest_exception_handlers(app)


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(INDEX_FILE)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
