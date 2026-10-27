"""개념·스테이지 단위 학습노트 및 최초 결과와 분리된 복습."""
import json
import uuid
import unicodedata
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedUserId
from app.db import get_session
from app.errors import QuizAPIError, invalid_submission, quiz_not_found
from app.models.quiz import QuizSet, QuizSubmission, QuizReview
from app.schemas.quiz import LearningNoteItem
from app.services.quiz_service import _note_items, answers_match
from app.services.learning_callbacks import get_concept_status
from app.timeutil import to_utc_iso

router = APIRouter(prefix="/api/v1/learning-notes", tags=["학습노트"])


class ReviewRecord(BaseModel):
    id: str
    submitted_answer: str
    is_correct: bool
    created_at: str


class NoteQuestion(LearningNoteItem):
    reviews: list[ReviewRecord]


class ConceptGroup(BaseModel):
    concept_id: str
    stage_id: str | None
    stage_ids: list[str | None]
    term: str
    latest_at: str
    concept_status: Literal["not_started", "in_progress", "passed"] | None
    questions: list[NoteQuestion]


class ConceptPage(BaseModel):
    items: list[ConceptGroup]
    total: int
    page: int
    page_size: int


@lru_cache(maxsize=1)
def concept_names():
    path = Path(__file__).resolve().parents[2] / "stage5_questions.json"
    return {row["concept_id"]: row["concept_name"] for row in json.loads(path.read_text(encoding="utf-8"))}


def review_dict(row):
    return dict(id=row.id, submitted_answer=row.submitted_answer, is_correct=row.is_correct,
                created_at=to_utc_iso(row.created_at))


@router.get("/concepts", response_model=ConceptPage)
async def list_concepts(
    user_id: AuthenticatedUserId,
    session: Annotated[AsyncSession, Depends(get_session)],
    note_filter: Annotated[Literal["all", "wrong", "correct"], Query(alias="filter")] = "all",
    stage_id: str | None = None,
    concept_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
):
    # 문항 페이지를 먼저 자르면 같은 개념의 탭이 누락되므로 그룹을 만든 뒤 페이지 처리한다.
    stmt = select(QuizSet, QuizSubmission).join(
        QuizSubmission, (QuizSubmission.quiz_set_id == QuizSet.id) & (QuizSubmission.user_id == user_id)
    ).where(QuizSet.user_id == user_id).order_by(
        QuizSubmission.created_at.desc(), QuizSubmission.id.desc(), QuizSet.id.desc()
    )
    if stage_id:
        stmt = stmt.where(QuizSet.stage_id == stage_id)
    if concept_id:
        stmt = stmt.where(QuizSet.concept_id == concept_id)
    groups = {}
    for quiz, submission in (await session.execute(stmt)).all():
        for item in _note_items(quiz, submission):
            if note_filter == "wrong" and item.is_correct is not False:
                continue
            if note_filter == "correct" and item.is_correct is not True:
                continue
            key = quiz.concept_id
            if key not in groups:
                groups[key] = dict(concept_id=quiz.concept_id, stage_id=quiz.stage_id,
                                   term=next((q["term"] for q in quiz.questions if q.get("term")), concept_names().get(quiz.concept_id, quiz.concept_id)),
                                   latest_at=item.created_at, stage_ids=[], questions=[])
            if quiz.stage_id not in groups[key]["stage_ids"]:
                groups[key]["stage_ids"].append(quiz.stage_id)
            groups[key]["questions"].append(item.model_dump())
    total = len(groups)
    # 전체 개념을 가나다순으로 정렬한 다음 페이지를 나눈다.
    ordered = sorted(groups.values(), key=lambda g: (
        unicodedata.normalize("NFC", g["term"]).strip().casefold(), g["concept_id"]
    ))
    selected = ordered[(page - 1) * 20:page * 20]
    submission_ids = {q["submission_id"] for g in selected for q in g["questions"]}
    reviews = {}
    if submission_ids:
        stmt = select(QuizReview).where(QuizReview.user_id == user_id, QuizReview.submission_id.in_(submission_ids)).order_by(QuizReview.created_at, QuizReview.id)
        for review in (await session.scalars(stmt)).all():
            reviews.setdefault((review.submission_id, review.question_index), []).append(review_dict(review))
    for group in selected:
        statuses = {}
        for sid in group["stage_ids"]:
            statuses[sid] = await get_concept_status(user_id=user_id, concept_id=group["concept_id"], stage_id=sid)
        group["concept_status"] = statuses[group["stage_id"]]
        for q in group["questions"]:
            q["concept_status"] = statuses[q["stage_id"]]
            q["reviews"] = reviews.get((q["submission_id"], q["question_index"]), [])
    return dict(items=selected, total=total, page=page, page_size=20)


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
