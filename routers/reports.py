from fastapi import APIRouter

from dependencies import CurrentUserId
from schemas.diagnostic import ReportResponse
from services.diagnostic_service import get_diagnostic_service

router = APIRouter(tags=["리포트"])


@router.get(
    "/reports/{id}",
    response_model=ReportResponse,
    response_model_exclude_none=True,
    summary="취약점 리포트 조회",
    description=(
        "생성 상태는 pending, processing, completed, failed 입니다. "
        "completed일 때 영역별 점수(domain_scores)와 LLM 분석(llm_report)을 함께 반환합니다. "
        "그래프는 domain_scores를, 텍스트는 llm_report를 사용합니다."
    ),
)
def get_report(id: str, user_id: CurrentUserId) -> ReportResponse:
    return get_diagnostic_service().get_report(id, user_id)
