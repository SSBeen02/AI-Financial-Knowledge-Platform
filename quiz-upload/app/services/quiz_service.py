"""동적 퀴즈 생성과 채점.

학습 관리 모듈에는 채점 결과와 생성 실패를 함수로 알립니다.
개념 통과 여부는 이 모듈의 테이블에 저장하지 않습니다.
생성에 실패하면 퀴즈 status를 failed로 반환하고 개념은 in_progress로 남깁니다.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import QuizGenerationError, idempotency_conflict, invalid_submission, quiz_not_found, quiz_not_ready
from app.models.quiz import QuizSet, QuizSetStatus, QuizSubmission
from app.schemas.quiz import (
    CreatedQuizSet,
    GeneratedQuizPayload,
    LearningContext,
    LearningModuleResult,
    LearningNoteItem,
    LearningNotesResponse,
    NoteFilter,
    QuizChoicePublic,
    QuizQuestionPublic,
    QuizQuestionResult,
    QuizSetPublicResponse,
    SubmitQuizResponse,
    SubmittedAnswer,
)
from app.services.learning_callbacks import report_quiz_generation_failed, report_quiz_result
from app.timeutil import to_utc_iso, utc_now
from database.settings import load_settings

logger = logging.getLogger("quiz")

PASS_CORRECT_COUNT = 2
PAGE_SIZE = 20
OX_TRUE = {"O", "TRUE", "Y", "YES", "맞다", "정답"}
OX_FALSE = {"X", "FALSE", "N", "NO", "틀리다", "오답"}

QuizGenerator = Callable[..., Awaitable[list[dict[str, Any]]]]

QUIZ_SYSTEM_PROMPT = """당신은 금융 개념을 확인하는 퀴즈 출제자입니다.
학습 맥락에 있는 내용만 사용하고, 맥락에 없는 수치나 제도는 만들지 않습니다.
반드시 JSON 객체 하나만 반환합니다. 설명 문장이나 코드 블록은 붙이지 않습니다.
questions 배열은 길이 3입니다.
- question_index 1과 2는 question_type "ox"입니다. choices는 key "O"와 "X" 두 개입니다. answer는 "O" 또는 "X"입니다.
- question_index 3은 question_type "situation"입니다. 학습자가 처한 상황을 제시하고, 행동 선택지 4개(key A, B, C, D) 중 알맞은 하나를 answer로 둡니다.
각 문항은 prompt, choices, answer, explanation을 모두 포함합니다.
explanation은 정답인 이유만 짧게 한국어로 씁니다.
"""

def _context_text(learning_context: LearningContext) -> str:
    if isinstance(learning_context, str):
        return learning_context
    return json.dumps(learning_context, ensure_ascii=False)


def resolved_stage_id(stage_id: str | None, learning_context: LearningContext) -> str | None:
    """인자 stage_id를 우선하고, 없으면 학습 맥락 안의 stage_id를 씁니다."""
    if isinstance(stage_id, str) and stage_id.strip():
        return stage_id.strip()
    return stage_id_from_context(learning_context)


def stage_id_from_context(learning_context: LearningContext) -> str | None:
    if isinstance(learning_context, dict):
        value = learning_context.get("stage_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _user_prompt(concept_id: str, learning_session_id: str, learning_context: LearningContext) -> str:
    return (
        f"concept_id: {concept_id}\n"
        f"learning_session_id: {learning_session_id}\n"
        "아래 학습 맥락으로 OX 2문항과 상황형 행동 선택 1문항을 만드세요.\n"
        f"{_context_text(learning_context)}"
    )


async def generate_quiz_with_openai(
    *,
    concept_id: str,
    learning_session_id: str,
    learning_context: LearningContext,
) -> list[dict[str, Any]]:
    """OPENAI_MODEL로 구조화된 퀴즈 3문항을 요청합니다."""
    settings = load_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY가 없어 퀴즈를 생성하지 못했습니다.")
    async with AsyncOpenAI(api_key=settings.openai_api_key, timeout=40.0, max_retries=1) as client:
        completion = await client.beta.chat.completions.parse(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": QUIZ_SYSTEM_PROMPT},
                {"role": "user", "content": _user_prompt(concept_id, learning_session_id, learning_context)},
            ],
            response_format=GeneratedQuizPayload,
        )
    if not completion.choices:
        raise RuntimeError("OpenAI 응답에 퀴즈가 없습니다.")
    message = completion.choices[0].message
    if getattr(message, "refusal", None):
        raise RuntimeError("OpenAI가 퀴즈 생성을 거절했습니다.")
    parsed = getattr(message, "parsed", None)
    if not isinstance(parsed, GeneratedQuizPayload):
        raise RuntimeError("OpenAI 응답을 구조화된 퀴즈로 읽지 못했습니다.")
    return [item.model_dump() for item in parsed.questions]


def _normalize_ox_answer(answer: str) -> str | None:
    token = answer.strip()
    upper = token.upper()
    if upper in OX_TRUE or token in OX_TRUE:
        return "O"
    if upper in OX_FALSE or token in OX_FALSE:
        return "X"
    return None


def normalize_questions(raw_questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OX 2개와 상황형 1개만 저장합니다."""
    if len(raw_questions) != 3:
        raise ValueError("퀴즈는 3문항이어야 합니다.")

    normalized: list[dict[str, Any]] = []
    for item in raw_questions:
        question_type = str(item.get("question_type", "")).strip().lower()
        prompt = str(item.get("prompt", "")).strip()
        explanation = str(item.get("explanation", "")).strip()
        if question_type not in {"ox", "situation"} or not prompt or not explanation:
            raise ValueError("문항 형식이 올바르지 않습니다.")
        try:
            question_index = int(item["question_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("question_index가 없습니다.") from exc

        choices = []
        for choice in item.get("choices") or []:
            key = str(choice.get("key", "")).strip()
            text = str(choice.get("text", "")).strip()
            if not key or not text:
                raise ValueError("보기가 비어 있습니다.")
            choices.append({"key": key, "text": text})
        if len(choices) < 2:
            raise ValueError("보기가 부족합니다.")

        answer = str(item.get("answer", "")).strip()
        if question_type == "ox":
            mapped = _normalize_ox_answer(answer)
            if mapped is None:
                raise ValueError("OX 정답이 올바르지 않습니다.")
            choice_map = {}
            for choice in choices:
                ox_key = _normalize_ox_answer(choice["key"]) or _normalize_ox_answer(choice["text"])
                if ox_key:
                    choice_map[ox_key] = choice["text"]
            if set(choice_map) != {"O", "X"}:
                raise ValueError("OX 보기는 O와 X여야 합니다.")
            choices = [
                {"key": "O", "text": choice_map["O"]},
                {"key": "X", "text": choice_map["X"]},
            ]
            answer = mapped
        else:
            keys = [choice["key"] for choice in choices]
            if len(keys) != len(set(keys)):
                raise ValueError("상황형 보기 키가 중복되었습니다.")
            if answer not in keys:
                raise ValueError("상황형 정답이 보기에 없습니다.")

        normalized.append(
            {
                "question_index": question_index,
                "question_type": question_type,
                "prompt": prompt,
                "choices": choices,
                "answer": answer,
                "explanation": explanation,
            }
        )

    indexes = [item["question_index"] for item in normalized]
    if sorted(indexes) != [1, 2, 3]:
        raise ValueError("문항 번호는 1, 2, 3이어야 합니다.")
    types = [item["question_type"] for item in sorted(normalized, key=lambda row: row["question_index"])]
    if types != ["ox", "ox", "situation"]:
        raise ValueError("OX 2문항 뒤에 상황형 1문항이 와야 합니다.")
    return sorted(normalized, key=lambda row: row["question_index"])


def answers_match(question: dict[str, Any], submitted: str) -> bool:
    given = submitted.strip()
    expected = str(question["answer"]).strip()
    if question["question_type"] == "ox":
        mapped = _normalize_ox_answer(given)
        return mapped is not None and mapped == expected
    if given.casefold() == expected.casefold():
        return True
    for choice in question["choices"]:
        if given.casefold() == str(choice["text"]).strip().casefold() and str(choice["key"]) == expected:
            return True
    return False


def _public_question(question: dict[str, Any]) -> QuizQuestionPublic:
    return QuizQuestionPublic(
        question_index=question["question_index"],
        question_type=question["question_type"],
        prompt=question["prompt"],
        choices=[QuizChoicePublic(key=choice["key"], text=choice["text"]) for choice in question["choices"]],
    )


def _public_quiz(quiz: QuizSet) -> QuizSetPublicResponse:
    questions = []
    if quiz.status == QuizSetStatus.COMPLETED.value:
        questions = [_public_question(question) for question in quiz.questions or []]
    return QuizSetPublicResponse(
        id=quiz.id,
        status=quiz.status,  # type: ignore[arg-type]
        concept_id=quiz.concept_id,
        learning_session_id=quiz.learning_session_id,
        stage_id=quiz.stage_id,
        questions=questions,
        created_at=to_utc_iso(quiz.created_at),
    )


def _ordered_answers(submitted_answers: list[SubmittedAnswer] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for item in submitted_answers:
        if isinstance(item, SubmittedAnswer):
            question_index = item.question_index
            answer = item.answer
        else:
            question_index = int(item["question_index"])
            answer = str(item["answer"])
        if question_index in seen:
            raise invalid_submission("question_index가 중복되었습니다.")
        seen.add(question_index)
        rows.append({"question_index": question_index, "answer": answer.strip()})
    if seen != {1, 2, 3}:
        raise invalid_submission("1번, 2번, 3번 답을 모두 보내야 합니다.")
    return sorted(rows, key=lambda row: row["question_index"])


def _grade(questions: list[dict[str, Any]], submitted_answers: list[dict[str, Any]]) -> tuple[list[bool], int, bool]:
    by_index = {item["question_index"]: item["answer"] for item in submitted_answers}
    flags = [answers_match(question, by_index[question["question_index"]]) for question in questions]
    correct_count = sum(1 for flag in flags if flag)
    return flags, correct_count, correct_count >= PASS_CORRECT_COUNT


def _submit_response(quiz: QuizSet, submission: QuizSubmission) -> SubmitQuizResponse:
    questions = list(quiz.questions or [])
    answers = {item["question_index"]: item["answer"] for item in submission.submitted_answers}
    flags = list(submission.is_correct_list)
    results = []
    for question, is_correct in zip(questions, flags, strict=True):
        results.append(
            QuizQuestionResult(
                question_index=question["question_index"],
                question_type=question["question_type"],
                prompt=question["prompt"],
                submitted_answer=answers[question["question_index"]],
                is_correct=bool(is_correct),
                answer=question["answer"],
                explanation=question["explanation"],
            )
        )
    learning_module_result = LearningModuleResult(
        submission_id=submission.id,
        concept_id=quiz.concept_id,
        correct_count=submission.correct_count,
        is_passed=submission.is_passed,
    )
    return SubmitQuizResponse(
        submission_id=submission.id,
        quiz_set_id=quiz.id,
        is_correct_list=[bool(flag) for flag in flags],
        correct_count=submission.correct_count,
        is_passed=submission.is_passed,
        results=results,
        learning_module_result=learning_module_result,
        created_at=to_utc_iso(submission.created_at),
    )


class QuizService:
    def __init__(self, generator: QuizGenerator | None = None):
        self._generator = generator or generate_quiz_with_openai

    async def create_quiz_set(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        session_id: str,
        concept_id: str,
        learning_context: LearningContext,
        stage_id: str | None = None,
        reference_chunk_ids: list[str] | None = None,
    ) -> CreatedQuizSet:
        if reference_chunk_ids:
            logger.debug("reference_chunk_ids %s개는 출제 검색에 쓰지 않습니다.", len(reference_chunk_ids))
        existing = await self._quiz_for_session(session, user_id, session_id)
        if existing is not None:
            return _created_quiz(existing)

        quiz = QuizSet(
            id=str(uuid.uuid4()),
            user_id=user_id,
            concept_id=concept_id,
            learning_session_id=session_id,
            stage_id=resolved_stage_id(stage_id, learning_context),
            questions=[],
            status=QuizSetStatus.PROCESSING.value,
            created_at=utc_now(),
        )
        session.add(quiz)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raced = await self._quiz_for_session(session, user_id, session_id)
            if raced is not None:
                return _created_quiz(raced)
            raise QuizGenerationError(
                quiz_set_id=quiz.id,
                concept_id=concept_id,
                message="퀴즈를 저장하지 못했습니다. 개념은 미통과(in_progress) 상태입니다.",
            )
        except Exception as exc:
            await session.rollback()
            raise QuizGenerationError(
                quiz_set_id=quiz.id,
                concept_id=concept_id,
                message="퀴즈를 저장하지 못했습니다. 개념은 미통과(in_progress) 상태입니다.",
            ) from exc

        try:
            if quiz.stage_id == "stage5":
                from app.services.stage5_bank import fixed_questions
                raw_questions = fixed_questions(concept_id)
            else:
                raw_questions = await self._generator(
                    concept_id=concept_id,
                    learning_session_id=session_id,
                    learning_context=learning_context,
                )
            quiz.questions = normalize_questions(raw_questions)
            quiz.status = QuizSetStatus.COMPLETED.value
            await session.commit()
        except Exception as exc:
            await session.rollback()
            failed = await session.get(QuizSet, quiz.id)
            if failed is None:
                raise QuizGenerationError(
                    quiz_set_id=quiz.id,
                    concept_id=concept_id,
                    message="퀴즈를 생성하지 못했습니다. 개념은 미통과(in_progress) 상태입니다.",
                ) from exc
            failed.questions = []
            failed.status = QuizSetStatus.FAILED.value
            await session.commit()
            logger.exception("퀴즈 생성 실패 concept_id=%s quiz_set_id=%s", concept_id, quiz.id)
            await _notify_generation_failed(session_id, user_id=user_id)
            return _created_quiz(failed)

        return _created_quiz(quiz)

    async def get_quiz_set(self, session: AsyncSession, *, quiz_set_id: str, user_id: str) -> QuizSetPublicResponse:
        quiz = await self._owned_quiz(session, quiz_set_id, user_id)
        return _public_quiz(quiz)

    async def submit_quiz_answers(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        quiz_set_id: str,
        submitted_answers: list[SubmittedAnswer] | list[dict[str, Any]],
        idempotency_key: str,
    ) -> SubmitQuizResponse:
        existing = await self._submission_by_key(session, user_id, idempotency_key)
        if existing is not None:
            if existing.quiz_set_id != quiz_set_id:
                raise idempotency_conflict()
            quiz = await self._owned_quiz(session, quiz_set_id, user_id)
            await _notify_quiz_result(quiz, existing)
            return _submit_response(quiz, existing)

        quiz = await self._owned_quiz(session, quiz_set_id, user_id)
        if quiz.status != QuizSetStatus.COMPLETED.value:
            raise quiz_not_ready()

        stored_answers = _ordered_answers(submitted_answers)
        flags, correct_count, is_passed = _grade(list(quiz.questions or []), stored_answers)
        submission = QuizSubmission(
            id=str(uuid.uuid4()),
            quiz_set_id=quiz.id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            submitted_answers=stored_answers,
            is_correct_list=flags,
            correct_count=correct_count,
            is_passed=is_passed,
            created_at=utc_now(),
        )
        session.add(submission)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raced = await self._submission_by_key(session, user_id, idempotency_key)
            if raced is None:
                raise
            if raced.quiz_set_id != quiz_set_id:
                raise idempotency_conflict()
            quiz = await self._owned_quiz(session, quiz_set_id, user_id)
            await _notify_quiz_result(quiz, raced)
            return _submit_response(quiz, raced)

        await _notify_quiz_result(quiz, submission)
        return _submit_response(quiz, submission)

    async def list_learning_notes(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        stage_id: str | None,
        concept_id: str | None,
        note_filter: NoteFilter,
        page: int,
    ) -> LearningNotesResponse:
        statement = (
            select(QuizSet, QuizSubmission)
            .outerjoin(QuizSubmission, QuizSubmission.quiz_set_id == QuizSet.id)
            .where(QuizSet.user_id == user_id)
            .order_by(QuizSet.created_at.desc(), QuizSubmission.created_at.desc())
        )
        if concept_id:
            statement = statement.where(QuizSet.concept_id == concept_id)
        if stage_id:
            statement = statement.where(QuizSet.stage_id == stage_id)

        rows = (await session.execute(statement)).all()
        items: list[LearningNoteItem] = []
        for quiz, submission in rows:
            items.extend(_note_items(quiz, submission))

        if note_filter == "correct":
            items = [item for item in items if item.is_correct is True]
        elif note_filter == "wrong":
            items = [item for item in items if item.is_correct is False]

        total = len(items)
        start = (page - 1) * PAGE_SIZE
        return LearningNotesResponse(
            items=items[start : start + PAGE_SIZE],
            page=page,
            page_size=PAGE_SIZE,
            total=total,
        )

    async def _quiz_for_session(self, session: AsyncSession, user_id: str, session_id: str) -> QuizSet | None:
        statement = select(QuizSet).where(
            QuizSet.user_id == user_id,
            QuizSet.learning_session_id == session_id,
        )
        return (await session.execute(statement)).scalar_one_or_none()

    async def _owned_quiz(self, session: AsyncSession, quiz_set_id: str, user_id: str) -> QuizSet:
        quiz = await session.get(QuizSet, quiz_set_id)
        if quiz is None or quiz.user_id != user_id:
            raise quiz_not_found()
        return quiz

    async def _submission_by_key(
        self,
        session: AsyncSession,
        user_id: str,
        idempotency_key: str,
    ) -> QuizSubmission | None:
        statement = select(QuizSubmission).where(
            QuizSubmission.user_id == user_id,
            QuizSubmission.idempotency_key == idempotency_key,
        )
        return (await session.execute(statement)).scalar_one_or_none()


async def _notify_generation_failed(session_id: str, *, user_id: str) -> None:
    try:
        await report_quiz_generation_failed(session_id, user_id=user_id)
    except Exception:
        logger.exception("report_quiz_generation_failed 실패 session_id=%s", session_id)


async def _notify_quiz_result(quiz: QuizSet, submission: QuizSubmission) -> None:
    try:
        await report_quiz_result(
            user_id=quiz.user_id,
            submission_id=submission.id,
            session_id=quiz.learning_session_id,
            concept_id=quiz.concept_id,
            stage_id=quiz.stage_id,
            correct_count=submission.correct_count,
            passed=submission.is_passed,
        )
    except Exception:
        logger.exception("report_quiz_result 실패 submission_id=%s", submission.id)


def _created_quiz(quiz: QuizSet) -> CreatedQuizSet:
    return CreatedQuizSet(
        id=quiz.id,
        status=quiz.status,
        concept_id=quiz.concept_id,
        learning_session_id=quiz.learning_session_id,
        stage_id=quiz.stage_id,
        created_at=to_utc_iso(quiz.created_at),
    )


def _note_items(quiz: QuizSet, submission: QuizSubmission | None) -> list[LearningNoteItem]:
    questions = sorted(quiz.questions or [], key=lambda item: item["question_index"])
    answers: dict[int, str] = {}
    flags: dict[int, bool] = {}
    if submission is not None:
        answers = {int(item["question_index"]): str(item["answer"]) for item in submission.submitted_answers}
        ordered = sorted(questions, key=lambda item: item["question_index"])
        for question, flag in zip(ordered, submission.is_correct_list, strict=False):
            flags[int(question["question_index"])] = bool(flag)

    created_at = to_utc_iso(submission.created_at if submission is not None else quiz.created_at)
    notes: list[LearningNoteItem] = []
    for question in questions:
        index = int(question["question_index"])
        submitted = submission is not None
        notes.append(
            LearningNoteItem(
                quiz_set_id=quiz.id,
                submission_id=submission.id if submission is not None else None,
                concept_id=quiz.concept_id,
                stage_id=quiz.stage_id,
                learning_session_id=quiz.learning_session_id,
                question_index=index,
                question_type=question["question_type"],
                prompt=question["prompt"],
                choices=[QuizChoicePublic(key=choice["key"], text=choice["text"]) for choice in question["choices"]],
                submitted_answer=answers.get(index) if submitted else None,
                is_correct=flags.get(index) if submitted else None,
                answer=question["answer"] if submitted else None,
                explanation=question["explanation"] if submitted else None,
                is_passed=submission.is_passed if submission is not None else None,
                created_at=created_at,
            )
        )
    return notes


async def create_quiz_set(
    session: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    concept_id: str,
    learning_context: LearningContext,
    stage_id: str | None = None,
    reference_chunk_ids: list[str] | None = None,
    generator: QuizGenerator | None = None,
) -> CreatedQuizSet:
    return await QuizService(generator).create_quiz_set(
        session,
        user_id=user_id,
        session_id=session_id,
        concept_id=concept_id,
        learning_context=learning_context,
        stage_id=stage_id,
        reference_chunk_ids=reference_chunk_ids,
    )


async def submit_quiz_answers(
    session: AsyncSession,
    *,
    user_id: str,
    quiz_set_id: str,
    submitted_answers: list[SubmittedAnswer] | list[dict[str, Any]],
    idempotency_key: str,
) -> SubmitQuizResponse:
    return await QuizService().submit_quiz_answers(
        session,
        user_id=user_id,
        quiz_set_id=quiz_set_id,
        submitted_answers=submitted_answers,
        idempotency_key=idempotency_key,
    )


def get_quiz_service() -> QuizService:
    return QuizService()
