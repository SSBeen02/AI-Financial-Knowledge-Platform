"""Temporary integration-test entry point for one-shot quiz generation failure.

Deploy this module instead of run_integration only while checking QZ-FR-06.
It reuses the normal app and its existing account/token settings.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
from threading import Lock
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict

import run_integration as normal
from app.services.quiz_service import QuizService
from chatbot import deps
from chatbot.integrations import SqlConceptStatusService
from server_auth import get_verified_user_id


logger = logging.getLogger("quiz")
ARM_TTL_SECONDS = 600
TestStage = Literal["stage1", "stage2", "stage3", "stage4"]
_lock = Lock()
_armed: dict[str, tuple[str, float]] = {}


class ArmQuizFailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_stage_id: TestStage
    concept_id: str


class ArmQuizFailureResponse(BaseModel):
    armed: bool
    concept_id: str
    expires_in_seconds: int


def _verify_test_account(user_id: str, test_token: str | None) -> None:
    allowed_user = os.getenv("INTEGRATION_TEST_USER_ID", "").strip()
    secret = os.getenv("INTEGRATION_TEST_STAGE_TOKEN", "").strip()
    if not allowed_user or len(secret) < 32:
        raise HTTPException(404, "통합시험 API가 비활성화되어 있습니다.")
    if not test_token or not hmac.compare_digest(test_token, secret):
        raise HTTPException(403, "통합시험 권한이 없습니다.")
    if not hmac.compare_digest(user_id, allowed_user):
        raise HTTPException(403, "허용된 테스트 계정이 아닙니다.")


def _consume_failure(user_id: str, concept_id: str) -> bool:
    with _lock:
        armed = _armed.get(user_id)
        if armed is None:
            return False
        expected_concept, expires_at = armed
        if time.monotonic() >= expires_at:
            del _armed[user_id]
            return False
        if expected_concept != concept_id:
            return False
        del _armed[user_id]
        return True


def _is_armed_for(user_id: str, concept_id: str) -> bool:
    with _lock:
        armed = _armed.get(user_id)
        return bool(armed and armed[0] == concept_id and time.monotonic() < armed[1])


_normal_register = normal.register_quiz_integration


def _register_with_failure_hook(application, **kwargs):
    adapter = _normal_register(application, **kwargs)
    original_create = adapter.service.create_quiz_set
    original_generator = adapter.service._generator
    original_reviewer = adapter.service._content_reviewer

    async def create_quiz_set(session, *, user_id, session_id, concept_id, **options):
        if _is_armed_for(user_id, concept_id):
            async def fail_once_or_generate(**generation_options):
                if _consume_failure(user_id, concept_id):
                    logger.warning(
                        "통합시험 퀴즈 생성 실패 유도 user_id=%s session_id=%s concept_id=%s",
                        user_id, session_id, concept_id,
                    )
                    raise RuntimeError("integration-test quiz generation failure")
                return await original_generator(**generation_options)

            service = QuizService(
                generator=fail_once_or_generate, content_reviewer=original_reviewer,
            )
            return await service.create_quiz_set(
                session, user_id=user_id, session_id=session_id,
                concept_id=concept_id, **options,
            )
        return await original_create(
            session, user_id=user_id, session_id=session_id,
            concept_id=concept_id, **options,
        )

    adapter.service.create_quiz_set = create_quiz_set
    return adapter


normal.register_quiz_integration = _register_with_failure_hook

router = APIRouter(prefix="/learning/integration-test/quiz-failure", tags=["integration-test"])


@router.post("/arm", response_model=ArmQuizFailureResponse)
def arm_quiz_failure(
    body: ArmQuizFailureRequest,
    user_id: Annotated[str, Depends(get_verified_user_id)],
    test_token: Annotated[str | None, Header(alias="X-Integration-Test-Token")] = None,
    service=Depends(deps.get_concept_status_service),
    catalog=Depends(deps.get_stage_catalog),
) -> ArmQuizFailureResponse:
    _verify_test_account(user_id, test_token)
    if not isinstance(service, SqlConceptStatusService):
        raise HTTPException(503, "학습 상태 서비스를 사용할 수 없습니다.")
    current_stage = service.get_current_stage(user_id)
    if current_stage != body.expected_stage_id:
        raise HTTPException(409, "현재 Stage가 요청과 다릅니다.")
    if body.concept_id not in {item.concept_id for item in catalog.stages[current_stage].concepts}:
        raise HTTPException(422, "현재 Stage에 없는 개념입니다.")
    with _lock:
        _armed[user_id] = (body.concept_id, time.monotonic() + ARM_TTL_SECONDS)
    return ArmQuizFailureResponse(
        armed=True, concept_id=body.concept_id, expires_in_seconds=ARM_TTL_SECONDS,
    )


@router.post("/cancel")
def cancel_quiz_failure(
    user_id: Annotated[str, Depends(get_verified_user_id)],
    test_token: Annotated[str | None, Header(alias="X-Integration-Test-Token")] = None,
) -> dict[str, bool]:
    _verify_test_account(user_id, test_token)
    with _lock:
        _armed.pop(user_id, None)
    return {"armed": False}


app = normal.app
app.include_router(router)
