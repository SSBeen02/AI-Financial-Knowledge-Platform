"""단독 앱 설정과 충돌하지 않는 통합 서버 등록 경계."""
import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from pretest.database.sql_repository import SqlDiagnosticRepository
from pretest.dependencies import CurrentUserId
from pretest.schemas.diagnostic import CurrentDiagnosticResponse
from pretest.services.diagnostic_service import DiagnosticService, get_diagnostic_service
from pretest.services.question_bank import load_questions


router = APIRouter(tags=["사전테스트"])


@router.get("/diagnostics/current", response_model=CurrentDiagnosticResponse)
def current_diagnostic(user_id: CurrentUserId,
                       service: Annotated[DiagnosticService, Depends(get_diagnostic_service)]):
    return service.current(user_id)


def get_pretest_service(request: Request) -> DiagnosticService:
    service = getattr(request.app.state, "pretest_service", None)
    if service is None:
        raise HTTPException(503, "사전테스트 모듈이 아직 준비되지 않았습니다.")
    return service


@dataclass
class PretestRuntime:
    service: DiagnosticService
    engine: object

    def close(self):
        self.engine.dispose()


def prepare_pretest_runtime():
    enabled = os.getenv("PRETEST_ENABLED", "false").strip().lower()
    if enabled not in {"true", "false"}:
        raise RuntimeError("PRETEST_ENABLED는 true 또는 false여야 합니다.")
    if enabled == "false":
        return None
    # 서비스 역할 키를 새로 배포하지 않고 기존 서버 DB 자격증명을 재사용한다.
    try:
        url = make_url(os.getenv("CHAT_DB_URL", ""))
    except Exception:
        raise RuntimeError("사전테스트 PostgreSQL 연결 설정을 확인하세요.") from None
    if url.drivername != "postgresql+psycopg":
        raise RuntimeError("사전테스트는 통합 서버 PostgreSQL 연결이 필요합니다.")
    mode = os.getenv("LLM_REPORT_MODE", "").strip().lower()
    if mode not in {"gemini", "openai"}:
        raise RuntimeError("운영 LLM_REPORT_MODE는 gemini 또는 openai로 설정하세요.")
    if not os.getenv("GEMINI_API_KEY" if mode == "gemini" else "OPENAI_API_KEY", "").strip():
        raise RuntimeError("선택한 사전테스트 리포트 제공자의 서버 API 키가 필요합니다.")
    # Each module has its own engine; keep rollout overlap below the shared session limit.
    engine = create_engine(url, pool_pre_ping=True, hide_parameters=True,
                           pool_size=1, max_overflow=0, pool_timeout=15)
    try:
        return PretestRuntime(DiagnosticService(load_questions(), SqlDiagnosticRepository(engine)), engine)
    except Exception:
        engine.dispose()
        raise
