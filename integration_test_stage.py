"""배포 통합시험 계정 전용 Stage 완료 API."""

from __future__ import annotations

import hmac
import os
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

from chatbot import deps
from chatbot.integrations import ConceptStatusError, SqlConceptStatusService
from server_auth import get_verified_user_id


router = APIRouter(prefix="/learning/integration-test", tags=["integration-test"])
TestStage = Literal["stage3", "stage4", "stage5"]


class CompleteStageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_stage_id: TestStage


class CompleteStageResponse(BaseModel):
    completed_stage_id: TestStage
    next_stage_id: Literal["stage4", "stage5"] | None
    previously_passed_count: int
    test_completed_count: int
    total_count: int
    event_count: int


@router.post("/complete-current-stage", response_model=CompleteStageResponse)
def complete_current_stage(
    body: CompleteStageRequest,
    user_id: Annotated[str, Depends(get_verified_user_id)],
    test_token: Annotated[str | None, Header(alias="X-Integration-Test-Token")] = None,
    service=Depends(deps.get_concept_status_service),
) -> CompleteStageResponse:
    allowed_user = os.getenv("INTEGRATION_TEST_USER_ID", "").strip()
    secret = os.getenv("INTEGRATION_TEST_STAGE_TOKEN", "").strip()
    if not allowed_user or len(secret) < 32:
        raise HTTPException(404, "통합시험 Stage 완료 API가 비활성화되어 있습니다.")
    if not test_token or not hmac.compare_digest(test_token, secret):
        raise HTTPException(403, "통합시험 권한이 없습니다.")
    if not hmac.compare_digest(user_id, allowed_user):
        raise HTTPException(403, "허용된 테스트 계정이 아닙니다.")
    if not isinstance(service, SqlConceptStatusService):
        raise HTTPException(503, "학습 상태 서비스를 사용할 수 없습니다.")
    try:
        result = service.complete_current_stage_for_integration_test(
            user_id, body.expected_stage_id
        )
    except ConceptStatusError as exc:
        raise HTTPException(409, str(exc)) from exc
    return CompleteStageResponse.model_validate(result)
