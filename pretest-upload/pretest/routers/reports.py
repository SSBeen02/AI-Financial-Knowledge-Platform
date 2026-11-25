from typing import Annotated
from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from pretest.dependencies import CurrentUserId
from pretest.schemas.diagnostic import ReportResponse
from pretest.services.diagnostic_service import DiagnosticService, get_diagnostic_service

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
def get_report(id: str, user_id: CurrentUserId,
               service: Annotated[DiagnosticService, Depends(get_diagnostic_service)]) -> ReportResponse:
    return service.get_report(id, user_id)


@router.post("/reports/{id}/retry", response_model=ReportResponse,
             response_model_exclude_none=True, status_code=status.HTTP_200_OK,
             summary="실패한 리포트 다시 생성")
def retry_report(id: str, user_id: CurrentUserId, background_tasks: BackgroundTasks,
                 response: Response,
                 service: Annotated[DiagnosticService, Depends(get_diagnostic_service)]) -> ReportResponse:
    if service.prepare_report_retry(id, user_id):
        background_tasks.add_task(service.generate_report, id, user_id)
        response.status_code = status.HTTP_202_ACCEPTED
    return service.get_report(id, user_id)
