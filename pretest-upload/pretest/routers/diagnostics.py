from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Response, status

from pretest.dependencies import CurrentUserId
from pretest.schemas.diagnostic import StartDiagnosticResponse, SubmitRequest, SubmitResponse
from pretest.services.diagnostic_service import DiagnosticService, get_diagnostic_service

router = APIRouter(tags=["사전테스트"])


@router.post("/diagnostics", response_model=StartDiagnosticResponse,
             status_code=status.HTTP_201_CREATED, summary="사전테스트 시작")
def start_diagnostic(user_id: CurrentUserId,
                     service: Annotated[DiagnosticService, Depends(get_diagnostic_service)]) -> StartDiagnosticResponse:
    return service.start(user_id)


@router.post("/diagnostics/{id}/submit", response_model=SubmitResponse,
             status_code=status.HTTP_202_ACCEPTED, summary="답안 접수 및 리포트 생성",
             description="Idempotency-Key 필수. 최초 접수는 202/processing, 동일 키·답안 재요청은 기존 상태 반환. report_id는 진단 id와 같습니다.")
def submit_diagnostic(
    id: UUID, payload: SubmitRequest, user_id: CurrentUserId,
    background_tasks: BackgroundTasks, response: Response,
    service: Annotated[DiagnosticService, Depends(get_diagnostic_service)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> SubmitResponse:
    result, created = service.submit(str(id), user_id, payload, idempotency_key)
    if created:
        background_tasks.add_task(service.generate_report, str(id), user_id)
    elif result.status != "processing":
        response.status_code = status.HTTP_200_OK
    return result
