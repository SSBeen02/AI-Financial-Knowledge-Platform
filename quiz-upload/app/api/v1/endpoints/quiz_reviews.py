"""기존 submission 기반 복습 계약을 통합 서버에 연결한다."""
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import AuthenticatedUserId
from app.db import get_session
from app.errors import QuizAPIError, invalid_submission, quiz_not_found
from app.models.quiz import QuizSet, QuizSubmission, QuizReview
from app.services.quiz_service import answers_match
from app.timeutil import to_utc_iso
router = APIRouter(prefix="/api/v1/learning-notes", tags=["학습노트 복습"])

class ReviewRecord(BaseModel):
    id: str
    submitted_answer: str
    is_correct: bool
    created_at: str


def review_dict(row):
    return dict(id=row.id, submitted_answer=row.submitted_answer, is_correct=row.is_correct,
                created_at=to_utc_iso(row.created_at))


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("answer", "idempotency_key")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("공백만 입력할 수 없습니다.")
        return value.strip()


@router.post("/submissions/{submission_id}/questions/{question_index}/reviews", response_model=ReviewRecord)
async def submit_review(
    submission_id: str, question_index: int, payload: ReviewRequest,
    user_id: AuthenticatedUserId,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    source = (await session.execute(select(QuizSet, QuizSubmission).join(QuizSubmission).where(
        QuizSubmission.id == submission_id, QuizSubmission.user_id == user_id, QuizSet.user_id == user_id
    ))).first()
    if source is None:
        raise quiz_not_found()
    quiz, submission = source
    question = next((q for q in quiz.questions if q["question_index"] == question_index), None)
    if question is None:
        raise quiz_not_found()
    if not any(int(a["question_index"]) == question_index for a in submission.submitted_answers):
        raise invalid_submission("최초 풀이가 있는 문항만 복습할 수 있습니다.")
    if payload.answer not in {str(c["key"]) for c in question["choices"]}:
        raise invalid_submission("문제의 보기 중 하나를 선택해 주세요.")

    async def existing():
        return await session.scalar(select(QuizReview).where(QuizReview.user_id == user_id, QuizReview.idempotency_key == payload.idempotency_key))

    def result(row):
        if (row.submission_id, row.question_index, row.submitted_answer) != (submission_id, question_index, payload.answer):
            raise QuizAPIError(409, "IDEMPOTENCY_CONFLICT", "같은 키로 다른 복습 답안을 제출할 수 없습니다.")
        return review_dict(row)

    row = await existing()
    if row is not None:
        return result(row)
    row = QuizReview(id=str(uuid.uuid4()), user_id=user_id, submission_id=submission_id,
                     question_index=question_index, idempotency_key=payload.idempotency_key,
                     submitted_answer=payload.answer, is_correct=answers_match(question, payload.answer))
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        row = await existing()
        if row is None:
            raise
    return result(row)


@router.get("/submissions/{submission_id}/questions/{question_index}/reviews", response_model=list[ReviewRecord])
async def list_reviews(
    submission_id: str, question_index: Annotated[int, Path(ge=1, le=3)],
    user_id: AuthenticatedUserId,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    source = (await session.execute(select(QuizSet, QuizSubmission).join(QuizSubmission).where(
        QuizSubmission.id == submission_id, QuizSubmission.user_id == user_id,
        QuizSet.user_id == user_id))).first()
    if source is None:
        raise quiz_not_found()
    quiz, submission = source
    if not any(int(a["question_index"]) == question_index for a in submission.submitted_answers):
        raise invalid_submission("최초 풀이가 있는 문항만 복습할 수 있습니다.")
    rows = (await session.scalars(select(QuizReview).where(
        QuizReview.user_id == user_id, QuizReview.submission_id == submission_id,
        QuizReview.question_index == question_index).order_by(
        QuizReview.created_at.desc(), QuizReview.id.desc()))).all()
    return [review_dict(row) for row in rows]
