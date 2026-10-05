"""로컬 수동 테스트 전용 API.

이 라우터는 ``DEV_ENABLE_TOOLS=true``일 때만 ``main_dev.py``가 등록한다.
통합·배포 앱은 이 모듈을 include하지 않는다.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from chatbot.concepts import StageCatalog
from chatbot.deps import get_chat_store, get_concept_status_service, get_stage_catalog
from chatbot.integrations import (
    ConceptStatusError,
    ConceptStatusService,
    CurrentUserId,
    SqlConceptStatusService,
)
from chatbot.store import ChatStore

StageId = Literal["stage1", "stage2", "stage3", "stage4", "stage5"]

router = APIRouter(prefix="/learning/dev", tags=["learning-dev"])


class DevStageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: StageId


class DevStageResponse(BaseModel):
    stage: StageId


class DevResetResponse(BaseModel):
    reset: bool
    stage: StageId


class DevConceptStatusOut(BaseModel):
    concept_id: str
    term: str
    term_full: str
    order: int
    status: Literal["not_started", "in_progress", "passed"]


class DevStatusResponse(BaseModel):
    current_stage: StageId
    stage: StageId
    concepts: list[DevConceptStatusOut]


def _local_status(service: ConceptStatusService) -> SqlConceptStatusService:
    if not isinstance(service, SqlConceptStatusService):
        raise HTTPException(
            status_code=404,
            detail="개발용 로컬 상태 서비스가 활성화되어 있지 않습니다.",
        )
    return service


@router.post("/stage", response_model=DevStageResponse)
def change_stage(
    request: DevStageIn,
    user_id: CurrentUserId,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
) -> DevStageResponse:
    service = _local_status(status_service)
    try:
        service.set_current_stage(user_id, request.stage)
    except ConceptStatusError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DevStageResponse(stage=service.get_current_stage(user_id))  # type: ignore[arg-type]


@router.post("/pass-all", response_model=DevStageResponse)
def pass_current_stage(
    user_id: CurrentUserId,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
) -> DevStageResponse:
    service = _local_status(status_service)
    current_stage = service.get_current_stage(user_id)
    service.pass_stage(user_id, current_stage)
    return DevStageResponse(stage=service.get_current_stage(user_id))  # type: ignore[arg-type]


@router.post("/reset", response_model=DevResetResponse)
def reset_user_data(
    user_id: CurrentUserId,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
    store: ChatStore = Depends(get_chat_store),
) -> DevResetResponse:
    service = _local_status(status_service)
    store.reset_user(user_id)
    service.reset_user(user_id)
    return DevResetResponse(reset=True, stage="stage1")


@router.get("/status", response_model=DevStatusResponse)
def read_status(
    user_id: CurrentUserId,
    stage: Annotated[StageId, Query()],
    status_service: ConceptStatusService = Depends(get_concept_status_service),
    catalog: StageCatalog = Depends(get_stage_catalog),
) -> DevStatusResponse:
    service = _local_status(status_service)
    statuses = service.get_statuses(user_id, stage)
    concepts = sorted(catalog.stages[stage].concepts, key=lambda item: item.order)
    return DevStatusResponse(
        current_stage=service.get_current_stage(user_id),  # type: ignore[arg-type]
        stage=stage,
        concepts=[
            DevConceptStatusOut(
                concept_id=concept.concept_id,
                term=concept.term,
                term_full=concept.term_full,
                order=concept.order,
                status=statuses[concept.concept_id],  # type: ignore[arg-type]
            )
            for concept in concepts
        ],
    )
