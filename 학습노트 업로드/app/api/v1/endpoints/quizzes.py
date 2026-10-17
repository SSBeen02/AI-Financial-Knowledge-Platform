from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedUserId
from app.db import get_session
from app.schemas.quiz import LearningNotesResponse, QuizSetPublicResponse, SubmitQuizRequest, SubmitQuizResponse
from app.services.quiz_service import QuizService, get_quiz_service

router = APIRouter(prefix="/api/v1", tags=["퀴즈·학습노트"])


@router.get(
    "/quiz-sets/{id}",
    response_model=QuizSetPublicResponse,
    summary="퀴즈 조회",
    description="생성 상태와 문제, 보기를 반환합니다. 정답과 해설은 포함하지 않습니다.",
)
async def get_quiz_set(
    id: str,
    user_id: AuthenticatedUserId,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> QuizSetPublicResponse:
    return await service.get_quiz_set(session, quiz_set_id=id, user_id=user_id)


@router.post(
    "/quiz-sets/{id}/submit",
    response_model=SubmitQuizResponse,
    summary="퀴즈 답안 제출",
    description=(
        "3문항 중 2문항 이상 맞으면 is_passed가 true입니다. "
        "같은 idempotency_key는 기존 채점 결과를 다시 반환합니다. "
        "learning_module_result는 학습 관리 모듈에 전달하는 내부 결과입니다."
    ),
)
async def submit_quiz(
    id: str,
    payload: SubmitQuizRequest,
    user_id: AuthenticatedUserId,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
) -> SubmitQuizResponse:
    return await service.submit_quiz_answers(
        session,
        user_id=user_id,
        quiz_set_id=id,
        submitted_answers=payload.submitted_answers,
        idempotency_key=payload.idempotency_key,
    )


@router.get(
    "/learning-notes",
    response_model=LearningNotesResponse,
    summary="학습노트 조회",
    description=(
        "quiz_sets와 quiz_submissions를 outer join해 풀이 이력을 반환합니다. "
        "아직 제출하지 않은 문항의 정오답은 null입니다."
    ),
)
async def get_learning_notes(
    user_id: AuthenticatedUserId,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[QuizService, Depends(get_quiz_service)],
    stage_id: str | None = None,
    concept_id: str | None = None,
    note_filter: Annotated[Literal["all", "correct", "wrong"], Query(alias="filter")] = "all",
    page: Annotated[int, Query(ge=1)] = 1,
) -> LearningNotesResponse:
    return await service.list_learning_notes(
        session,
        user_id=user_id,
        stage_id=stage_id,
        concept_id=concept_id,
        note_filter=note_filter,
        page=page,
    )
