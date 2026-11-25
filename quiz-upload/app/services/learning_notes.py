"""개념별 학습노트: 기존 풀이·복습 테이블을 조회한다."""
import asyncio
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedUserId
from app.db import get_session
from app.models.quiz import QuizReview, QuizSet, QuizSubmission
from app.schemas.quiz import LearningNoteItem
from app.services.quiz_language import localize_quiz_text
from app.services.quiz_service import _note_items
from app.timeutil import to_utc_iso

router = APIRouter(prefix="/api/v1/learning-notes", tags=["학습노트"])


class ReviewRecord(BaseModel):
    id: str
    submitted_answer: str
    is_correct: bool
    created_at: str


class NoteQuestion(LearningNoteItem):
    attempt_number: int
    concept_status: Literal["not_started", "in_progress", "passed"] | None = None
    reviews: list[ReviewRecord]


class ConceptGroup(BaseModel):
    concept_id: str
    stage_id: str | None
    stage_ids: list[str | None]
    term: str
    latest_at: str
    total_attempts: int
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


async def get_concept_status(*, user_id: str, concept_id: str, stage_id: str | None):
    if not stage_id:
        return None
    try:
        from chatbot.deps import get_concept_status_service
        service = get_concept_status_service()
    except (ImportError, RuntimeError, ValidationError):
        # The standalone quiz app has no learning-status module.
        return None
    return await asyncio.to_thread(service.get_concept_status, user_id, concept_id, stage_id)


@router.get("/concepts", response_model=ConceptPage)
async def list_concepts(
    user_id: AuthenticatedUserId,
    session: Annotated[AsyncSession, Depends(get_session)],
    note_filter: Annotated[Literal["all", "wrong", "correct"], Query(alias="filter")] = "all",
    sort_order: Annotated[Literal["alphabetical", "latest"], Query(alias="sort")] = "alphabetical",
    stage_id: str | None = None,
    concept_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
) -> ConceptPage:
    stmt = select(QuizSet, QuizSubmission).join(
        QuizSubmission, (QuizSubmission.quiz_set_id == QuizSet.id) & (QuizSubmission.user_id == user_id)
    ).where(QuizSet.user_id == user_id).order_by(
        QuizSubmission.created_at.desc(), QuizSubmission.id.desc(), QuizSet.id.desc()
    )
    if stage_id:
        stmt = stmt.where(QuizSet.stage_id == stage_id)
    if concept_id:
        stmt = stmt.where(QuizSet.concept_id == concept_id)
    rows = []
    for quiz, submission in (await session.execute(stmt)).all():
        items = [item for item in _note_items(quiz, submission)
                 if item.submitted_answer is not None and item.is_correct is not None]
        if items:
            rows.append((quiz, submission, items))

    attempt_numbers, stage_attempts, concept_attempts = {}, {}, {}
    for quiz, submission, _ in reversed(rows):
        key = (quiz.concept_id, quiz.stage_id)
        stage_attempts[key] = stage_attempts.get(key, 0) + 1
        attempt_numbers[submission.id] = stage_attempts[key]
        concept_attempts[quiz.concept_id] = concept_attempts.get(quiz.concept_id, 0) + 1

    groups, latest_times = {}, {}
    for quiz, submission, items in rows:
        for item in items:
            if note_filter == "wrong" and item.is_correct is not False:
                continue
            if note_filter == "correct" and item.is_correct is not True:
                continue
            key = quiz.concept_id
            if key not in groups:
                term = next((q["term"] for q in quiz.questions if q.get("term")),
                            concept_names().get(key, key))
                term = re.sub(r"\s*\([A-Za-z][A-Za-z -]*\)", "", term)
                latest_times[key] = submission.created_at
                groups[key] = dict(concept_id=key, stage_id=quiz.stage_id,
                                   term=localize_quiz_text(term), latest_at=item.created_at,
                                   total_attempts=concept_attempts[key], stage_ids=[], questions=[])
            if quiz.stage_id not in groups[key]["stage_ids"]:
                groups[key]["stage_ids"].append(quiz.stage_id)
            groups[key]["questions"].append(dict(item.model_dump(), attempt_number=attempt_numbers[submission.id]))

    total = len(groups)
    if sort_order == "latest":
        ordered = sorted(groups.values(), key=lambda g: (latest_times[g["concept_id"]], g["concept_id"]), reverse=True)
    else:
        ordered = sorted(groups.values(), key=lambda g: (
            unicodedata.normalize("NFC", g["term"]).strip().casefold(), g["concept_id"]
        ))
    selected = ordered[(page - 1) * 20:page * 20]
    submission_ids = {q["submission_id"] for g in selected for q in g["questions"]}
    reviews = {}
    if submission_ids:
        stmt = select(QuizReview).where(QuizReview.user_id == user_id,
                                        QuizReview.submission_id.in_(submission_ids)).order_by(
                                            QuizReview.created_at, QuizReview.id)
        for review in (await session.scalars(stmt)).all():
            record = ReviewRecord(id=review.id, submitted_answer=review.submitted_answer,
                                  is_correct=review.is_correct, created_at=to_utc_iso(review.created_at))
            reviews.setdefault((review.submission_id, review.question_index), []).append(record)
    for group in selected:
        statuses = {sid: await get_concept_status(user_id=user_id, concept_id=group["concept_id"], stage_id=sid)
                    for sid in group["stage_ids"]}
        group["concept_status"] = statuses[group["stage_id"]]
        for q in group["questions"]:
            q["concept_status"] = statuses[q["stage_id"]]
            q["reviews"] = reviews.get((q["submission_id"], q["question_index"]), [])
    return ConceptPage(items=selected, total=total, page=page, page_size=20)
