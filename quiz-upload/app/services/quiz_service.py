"""동적 퀴즈 생성과 채점.

학습 관리 모듈에는 채점 결과와 생성 실패를 함수로 알립니다.
개념 통과 여부는 이 모듈의 테이블에 저장하지 않습니다.
생성에 실패하면 퀴즈 status를 failed로 반환하고 개념은 in_progress로 남깁니다.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import time
import unicodedata
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from difflib import SequenceMatcher

from pydantic import ValidationError
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import QuizAPIError, QuizGenerationError, idempotency_conflict, invalid_submission, quiz_not_found, quiz_not_ready
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
from app.services.fallback_bank import select_fallback_set
from app.services.learning_callbacks import report_quiz_generation_failed, report_quiz_result
from app.services.quiz_content import CONTENT_REVIEW_TIMEOUT_SECONDS, QuizContentError, QuizContentReviewUnavailable, review_quiz_content
from app.services.quiz_language import QuizLanguageError, localize_quiz_text, validate_korean_text
from app.services.quiz_tone import choice_in_polite, explanation_in_polite, question_in_polite
from app.timeutil import to_utc_iso, utc_now
from database.settings import load_settings

logger = logging.getLogger("quiz")

PASS_CORRECT_COUNT = 2
PAGE_SIZE = 20
NOVELTY_GENERATION_ATTEMPTS = 2
MAX_GENERATION_ATTEMPTS = 3  # 최초 1회 + 형식/내용 재생성 최대 2회
GENERATION_TIMEOUT_SECONDS = 60.0
AI_REQUEST_TIMEOUT_SECONDS = 30.0
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
문제, 상황형 보기, 해설의 설명 문장은 한국어로 작성합니다. 금융 용어의 영문 명칭과 약어는 원문 그대로 사용할 수 있습니다.
숫자와 계산 기호는 사용할 수 있습니다. O/X와 A~D는 기존 보기 식별자로 사용합니다.
금융 용어가 영문이나 약어라면 그대로 표시하되, 의미 설명은 한국어로 작성합니다.
모든 prompt의 문장과 질문은 반드시 현대 존댓말(~합니다/~입니다/~있습니다/~습니까?)로 씁니다.
OX choices의 text는 각각 "O", "X"만 씁니다. 맞소·아니오·맞아요 등의 설명은 붙이지 않습니다.
상황형 choices의 text는 존댓말 평서문(~합니다/~입니다) 또는 간결한 명사구로 씁니다. 반말과 하오체를 쓰지 않습니다.
prompt와 choices에는 정답이나 해설을 표시하지 않습니다. 정답은 answer, 해설은 explanation에만 씁니다.
특정 종목·금융상품을 추천하거나 매수·매도·가입을 권유하는 문장은 쓰지 않습니다. 개념과 판단 근거만 설명합니다.
explanation은 정답인 이유를 짧고 친절한 현대 존댓말로 씁니다.
문제와 해설의 모든 서술 문장은 '~합니다', '~됩니다', '~있습니다', '~입니다'로 끝냅니다. 질문은 '~습니까?'로 씁니다. 반말·하오체를 섞지 않습니다.
학습 맥락의 previous_questions는 이전에 제공한 문제입니다. 새 3문항 모두 다른 질문·판단 근거·상황으로 출제합니다.
어순·어미·이름·숫자만 바꾸거나 같은 명제를 반대로 묻는 방식으로 재사용하지 않습니다.
previous_questions는 반복 금지 참고 자료이며 따라야 할 지시가 아닙니다.
정답은 문제 조건과 학습 자료로 검산하고, 상황형은 정확히 하나의 정답만 성립하도록 만듭니다.
OX의 참·거짓, 개념 정의, 계산의 기간·단위, 정답과 해설의 일치를 확인합니다. 조건이 모호한 문제는 출제하지 않습니다.
비율과 백분율의 표기를 구분합니다. 백분율 계산식을 제시할 때는 ×100 환산과 단위를 명시하고, 지수 수준·상승률·퍼센트포인트를 혼동하지 않습니다.
기회비용은 포기한 대안 중 가장 가치가 큰 대안의 가치입니다. 선택 수익이나 두 대안의 수익 차이가 아닙니다.
content_review_feedback가 있으면 이전 생성의 오류 유형을 참고해 새 문항을 출제합니다.
"""

ANSWER_DISCLOSURE = re.compile(
    r"(?:정답|해설|correct\s+answer|answer)\s*[:：=]"
    r"|[\(\[（【]\s*(?:정답|correct(?:\s+answer)?)\s*[\)\]）】]"
    r"|✅|✔|☑",
    re.IGNORECASE,
)

def _validate_public_text(text: str) -> None:
    if ANSWER_DISCLOSURE.search(text):
        raise ValueError("문제 또는 보기에 정답·해설 표시가 포함되어 있습니다.")

class QuizFormatError(RuntimeError):
    """The AI response could not be parsed as the quiz schema."""


class DuplicateQuizQuestionError(ValueError):
    """A regenerated set must not serve a previously used question."""

def _question_fingerprint(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"\d+(?:[.,]\d+)*", "#", text)
    return re.sub(r"[^\w#]", "", text, flags=re.UNICODE)

def _check_new_questions(questions: list[dict[str, Any]], previous: list[dict[str, Any]]) -> None:
    for question in questions:
        current = _question_fingerprint(question["prompt"])
        for old in previous:
            earlier = _question_fingerprint(str(old.get("prompt", "")))
            if not earlier:
                continue
            if current == earlier or SequenceMatcher(None, current, earlier, autojunk=False).ratio() >= 0.82:
                raise DuplicateQuizQuestionError("이전에 제공한 문제와 동일하거나 유사한 문항이 생성되었습니다.")

def _context_with_previous(learning_context: LearningContext, previous: list[dict[str, Any]]) -> LearningContext:
    if not previous:
        return learning_context
    context = dict(learning_context) if isinstance(learning_context, dict) else {"learning_context": learning_context}
    context["previous_questions"] = [
        {key: question.get(key) for key in ("question_type", "prompt", "choices", "answer")}
        for question in previous
    ]
    return context


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


def _generation_indexes(learning_context: LearningContext) -> list[int]:
    request = learning_context.get("quiz_repair_request") if isinstance(learning_context, dict) else None
    if request is None:
        return [1, 2, 3]
    indexes = request.get("question_indexes") if isinstance(request, dict) else None
    if (not isinstance(indexes, list) or not indexes or any(type(i) is not int for i in indexes)
            or len(set(indexes)) != len(indexes) or not set(indexes) <= {1, 2, 3}):
        raise QuizFormatError("부분 재생성 문항 번호가 올바르지 않습니다.")
    return sorted(indexes)


def _user_prompt(concept_id: str, learning_session_id: str, learning_context: LearningContext) -> str:
    indexes = _generation_indexes(learning_context)
    instruction = "아래 학습 맥락으로 OX 2문항과 상황형 행동 선택 1문항을 만드세요."
    if indexes != [1, 2, 3]:
        instruction = f"문항 번호 {indexes}만 새로 출제하세요. 1·2번은 OX, 3번은 상황형입니다. 번호를 바꾸지 마세요."
    return (
        f"concept_id: {concept_id}\n"
        f"learning_session_id: {learning_session_id}\n"
        f"{instruction}\n"
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
    indexes = _generation_indexes(learning_context)
    system_prompt = QUIZ_SYSTEM_PROMPT
    if indexes != [1, 2, 3]:
        system_prompt = system_prompt.replace("questions 배열은 길이 3입니다.", f"questions 배열 길이는 {len(indexes)}이며 문항 번호는 {indexes}만 포함합니다.")
        system_prompt = system_prompt.replace("새 3문항 모두", "새 문항 모두")
        system_prompt += "\n부분 재생성입니다. quiz_repair_request의 요청 번호만 반환합니다. retained_questions는 이미 통과한 문항이므로 바꾸거나 응답에 넣지 않습니다. 새 문항은 보존 문항과 중복하지 않고 다른 문항의 정답에 의존하지 않도록 독립적으로 출제합니다."
    async with AsyncOpenAI(api_key=settings.openai_api_key, timeout=AI_REQUEST_TIMEOUT_SECONDS, max_retries=1) as client:
        try:
            completion = await client.beta.chat.completions.parse(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": _user_prompt(concept_id, learning_session_id, learning_context)},
                ],
                response_format=GeneratedQuizPayload,
            )
        except ValidationError as exc:
            raise QuizFormatError("OpenAI 문항 형식을 검증하지 못했습니다.") from exc
    if not completion.choices:
        raise RuntimeError("OpenAI 응답에 퀴즈가 없습니다.")
    message = completion.choices[0].message
    if getattr(message, "refusal", None):
        raise RuntimeError("OpenAI가 퀴즈 생성을 거절했습니다.")
    parsed = getattr(message, "parsed", None)
    if not isinstance(parsed, GeneratedQuizPayload):
        raise QuizFormatError("OpenAI 응답을 구조화된 퀴즈로 읽지 못했습니다.")
    questions = [item.model_dump() for item in parsed.questions]
    if {item["question_index"] for item in questions} - set(indexes):
        raise QuizFormatError("요청한 문항 번호와 OpenAI 응답이 일치하지 않습니다.")
    return questions


def _normalize_ox_answer(answer: str) -> str | None:
    token = answer.strip()
    upper = token.upper()
    if upper in OX_TRUE or token in OX_TRUE:
        return "O"
    if upper in OX_FALSE or token in OX_FALSE:
        return "X"
    return None


def normalize_questions(raw_questions: list[dict[str, Any]], *, expected_indexes: list[int] | None = None) -> list[dict[str, Any]]:
    """OX 2개와 상황형 1개만 저장합니다."""
    expected = [1, 2, 3] if expected_indexes is None else sorted(expected_indexes)
    if not expected or len(set(expected)) != len(expected) or not set(expected) <= {1, 2, 3}:
        raise ValueError("출제 대상 문항 번호가 올바르지 않습니다.")
    raw_questions = [item.model_dump() for item in GeneratedQuizPayload(questions=raw_questions).questions]
    if len(raw_questions) != len(expected):
        raise ValueError("요청한 문항 수와 응답이 일치하지 않습니다.")

    normalized: list[dict[str, Any]] = []
    for item in raw_questions:
        question_type = str(item.get("question_type", "")).strip().lower()
        # Apply the same localization to generated, fixed and stored quiz text.
        prompt = localize_quiz_text(str(item.get("prompt", "")).strip())
        explanation = localize_quiz_text(str(item.get("explanation", "")).strip())
        field_prefix = f"questions[{item['question_index']}]"
        _validate_public_text(prompt)
        validate_korean_text(prompt, field=field_prefix + ".prompt")
        validate_korean_text(explanation, field=field_prefix + ".explanation")
        prompt = question_in_polite(prompt, strict=True)
        explanation = explanation_in_polite(explanation, strict=True)
        if question_type not in {"ox", "situation"} or not prompt or not explanation:
            raise ValueError("문항 형식이 올바르지 않습니다.")
        _validate_public_text(prompt)
        validate_korean_text(prompt)
        validate_korean_text(explanation)
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
            _validate_public_text(text)
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
                {"key": "O", "text": "O"},
                {"key": "X", "text": "X"},
            ]
            answer = mapped
        else:
            for index, choice in enumerate(choices):
                localized = localize_quiz_text(choice["text"])
                field = f"{field_prefix}.choices[{index}].text"
                validate_korean_text(localized, allow_numeric=True, allow_finance_terms=True, field=field)
                choice["text"] = choice_in_polite(localized, strict=True)
                validate_korean_text(choice["text"], allow_numeric=True, allow_finance_terms=True, field=field)
            keys = [choice["key"] for choice in choices]
            if len(keys) != len(set(keys)):
                raise ValueError("상황형 보기 키가 중복되었습니다.")
            if sorted(keys) != ["A", "B", "C", "D"]:
                raise ValueError("상황형 보기는 A~D 4개여야 합니다.")
            labels = [re.sub(r"\s+", "", unicodedata.normalize("NFKC", c["text"])).casefold() for c in choices]
            if len(set(labels)) != 4:
                raise ValueError("상황형 보기 내용이 중복되었습니다.")
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
    if sorted(indexes) != expected:
        raise ValueError("요청한 문항 번호와 응답이 일치하지 않습니다.")
    types = [item["question_type"] for item in sorted(normalized, key=lambda row: row["question_index"])]
    if types != ["situation" if index == 3 else "ox" for index in expected]:
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


def _quiz_display_text(
    text: str, *, allow_numeric: bool = False, fallback: str | None = None,
) -> str:
    localized = localize_quiz_text(text)
    try:
        validate_korean_text(localized, allow_numeric=allow_numeric, allow_finance_terms=allow_numeric)
    except ValueError as exc:
        if fallback is not None:
            return fallback
        raise QuizAPIError(
            409, "QUIZ_LANGUAGE_UNSUPPORTED",
            "저장된 퀴즈에 한국어로 표시할 수 없는 내용이 있습니다.",
        ) from exc
    return localized


def _public_question(question: dict[str, Any]) -> QuizQuestionPublic:
    return QuizQuestionPublic(
        question_index=question["question_index"],
        question_type=question["question_type"],
        prompt=question_in_polite(_quiz_display_text(question["prompt"])),
        choices=[QuizChoicePublic(key=choice["key"], text=choice["key"] if question["question_type"] == "ox" else choice_in_polite(_quiz_display_text(choice["text"], allow_numeric=True))) for choice in question["choices"]],
    )


def has_playable_korean_text(question: dict[str, Any]) -> bool:
    choices = question["choices"]
    if not choices or any(choice["key"] not in {"O", "X", "A", "B", "C", "D"} for choice in choices):
        return False
    try:
        _public_question(question)
    except QuizAPIError as exc:
        if exc.code != "QUIZ_LANGUAGE_UNSUPPORTED":
            raise
        return False
    return True


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
                prompt=question_in_polite(_quiz_display_text(question["prompt"])),
                submitted_answer=answers[question["question_index"]],
                is_correct=bool(is_correct),
                answer=question["answer"],
                explanation=explanation_in_polite(_quiz_display_text(question["explanation"])),
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
    def __init__(self, generator: QuizGenerator | None = None, *, content_reviewer: Callable[..., Awaitable[None]] | None = None):
        self._generator = generator or generate_quiz_with_openai
        self._content_reviewer = content_reviewer or review_quiz_content

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
        quiz_id = quiz.id
        session.add(quiz)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raced = await self._quiz_for_session(session, user_id, session_id)
            if raced is not None:
                return _created_quiz(raced)
            raise QuizGenerationError(
                quiz_set_id=quiz_id,
                concept_id=concept_id,
                message="퀴즈를 저장하지 못했습니다. 개념은 미통과(in_progress) 상태입니다.",
            )
        except Exception as exc:
            await session.rollback()
            raise QuizGenerationError(
                quiz_set_id=quiz_id,
                concept_id=concept_id,
                message="퀴즈를 저장하지 못했습니다. 개념은 미통과(in_progress) 상태입니다.",
            ) from exc

        started = time.perf_counter()
        stage_for_log = quiz.stage_id
        source = "stage5" if stage_for_log == "stage5" else "dynamic"
        attempts = 0
        try:
            if quiz.stage_id == "stage5":
                from app.services.stage5_bank import fixed_questions
                raw_questions = fixed_questions(concept_id)
                questions = normalize_questions(raw_questions)
            else:
                statement = select(QuizSet.questions).where(
                    QuizSet.user_id == user_id,
                    QuizSet.concept_id == concept_id,
                    QuizSet.status == QuizSetStatus.COMPLETED.value,
                    QuizSet.id != quiz.id,
                )
                previous = [question for group in (await session.execute(statement)).scalars().all() for question in (group or [])]
                excluded = list(previous)

                async def generate_validated():
                    nonlocal attempts
                    retained: dict[int, dict[str, Any]] = {}
                    feedback: list[dict[str, Any]] = []
                    duplicates = 0
                    for attempt in range(MAX_GENERATION_ATTEMPTS):
                        attempts = attempt + 1
                        targets = sorted({1, 2, 3} - set(retained))
                        # These keys are controlled by this service, not supplied learning data.
                        base_context = learning_context
                        if isinstance(base_context, dict):
                            base_context = {k: v for k, v in base_context.items()
                                            if k not in {"quiz_repair_request", "content_review_feedback"}}
                        generation_context = _context_with_previous(base_context, excluded)
                        if feedback or retained:
                            generation_context = dict(generation_context) if isinstance(generation_context, dict) else {"learning_context": generation_context}
                            if feedback:
                                generation_context["content_review_feedback"] = copy.deepcopy(feedback)
                            if retained:
                                generation_context["quiz_repair_request"] = {
                                    "question_indexes": targets,
                                    "retained_questions": copy.deepcopy([retained[i] for i in sorted(retained)]),
                                }
                        try:
                            raw_questions = await self._generator(
                                concept_id=concept_id,
                                learning_session_id=session_id,
                                learning_context=generation_context,
                            )
                        except QuizFormatError:
                            if attempts == MAX_GENERATION_ATTEMPTS:
                                raise
                            continue

                        # Validate each requested question so one bad field cannot discard its peers.
                        by_index: dict[int, list[dict[str, Any]]] = {i: [] for i in targets}
                        for item in raw_questions if isinstance(raw_questions, list) else []:
                            if not isinstance(item, dict):
                                continue
                            try:
                                index = int(item.get("question_index"))
                            except (TypeError, ValueError):
                                continue
                            if index in by_index:
                                by_index[index].append(item)
                        candidate = []
                        feedback = []
                        duplicate_found = False
                        for index in targets:
                            try:
                                batch = normalize_questions(by_index[index], expected_indexes=[index])
                                _check_new_questions(batch, previous + list(retained.values()))
                            except ValueError as error:
                                code = "invalid_format"
                                if isinstance(error, DuplicateQuizQuestionError):
                                    code = "duplicate_question"
                                    duplicate_found = True
                                elif isinstance(error, QuizLanguageError):
                                    code = "invalid_language"
                                    logger.warning(
                                        "퀴즈 언어 검증 실패 quiz_set_id=%s concept_id=%s stage_id=%s "
                                        "attempt=%s field=%s reason=%s rejected_tokens=%s codepoints=%s text_sha256=%s",
                                        quiz_id, concept_id, stage_for_log, attempts, error.field, error.reason,
                                        json.dumps(error.rejected_tokens, ensure_ascii=True),
                                        json.dumps(error.codepoints), error.text_sha256,
                                    )
                                logger.warning(
                                    "퀴즈 문항 검증 실패 quiz_set_id=%s concept_id=%s stage_id=%s attempt=%s question_index=%s reason=%s",
                                    quiz_id, concept_id, stage_for_log, attempts, index, type(error).__name__,
                                )
                                feedback.append({"question_index": index, "codes": [code]})
                            else:
                                candidate.extend(batch)

                        if candidate:
                            try:
                                await asyncio.wait_for(self._content_reviewer(
                                    quiz_set_id=quiz_id, concept_id=concept_id,
                                    learning_context=learning_context, questions=copy.deepcopy(candidate),
                                ), timeout=CONTENT_REVIEW_TIMEOUT_SECONDS)
                            except QuizContentError as error:
                                reviewed = {q["question_index"] for q in candidate}
                                approved = set(error.approved_question_indexes)
                                rejected = {item["question_index"] for item in error.issues}
                                if (not error.issues or not rejected <= reviewed or not approved <= reviewed
                                        or approved & rejected):
                                    raise QuizContentReviewUnavailable("문항별 승인·거부 결과가 일치하지 않습니다.") from None
                                # Only explicit approvals from a complete review can survive a rejection.
                                for question in candidate:
                                    if question["question_index"] in approved:
                                        retained[question["question_index"]] = question
                                feedback.extend(copy.deepcopy(error.issues))
                                for index in sorted(reviewed - approved - rejected):
                                    feedback.append({"question_index": index, "codes": ["review_not_approved"]})
                                logger.warning(
                                    "퀴즈 내용 검증 실패 quiz_set_id=%s concept_id=%s stage_id=%s attempt=%s issues=%s approved_indexes=%s",
                                    quiz_id, concept_id, stage_for_log, attempts,
                                    json.dumps(error.issues, ensure_ascii=True), sorted(approved),
                                )
                            else:
                                for question in candidate:
                                    retained[question["question_index"]] = question

                        if set(retained) == {1, 2, 3}:
                            return normalize_questions([retained[i] for i in (1, 2, 3)])
                        if duplicate_found:
                            duplicates += 1
                            if duplicates >= NOVELTY_GENERATION_ATTEMPTS:
                                raise DuplicateQuizQuestionError("이전에 제공한 문항이 반복 생성되었습니다.")
                        logger.info(
                            "퀴즈 부분 재생성 대기 quiz_set_id=%s attempt=%s retained_indexes=%s pending_indexes=%s",
                            quiz_id, attempts, sorted(retained), sorted({1, 2, 3} - set(retained)),
                        )
                    raise ValueError("모든 문항의 검증을 완료하지 못했습니다.")

                try:
                    questions = await asyncio.wait_for(generate_validated(), timeout=GENERATION_TIMEOUT_SECONDS)
                except Exception as generation_error:
                    # Re-read completed history: another session may have completed during generation.
                    # Row locks serialize fallback selection for the same user/concept on PostgreSQL.
                    await session.execute(select(QuizSet.id).where(
                        QuizSet.user_id == user_id, QuizSet.concept_id == concept_id,
                    ).order_by(QuizSet.id).with_for_update())
                    served = [question for group in (await session.execute(statement)).scalars().all() for question in (group or [])]
                    fallback = select_fallback_set(
                        concept_id=concept_id, stage_id=quiz.stage_id, previous_questions=served,
                        normalizer=normalize_questions, novelty_checker=_check_new_questions,
                    )
                    if fallback is None:
                        raise
                    fallback_id, questions = fallback
                    source = "fallback"
                    logger.warning(
                        "퀴즈 예비 문항 대체 quiz_set_id=%s concept_id=%s stage_id=%s fallback_set_id=%s attempts=%s generation_reason=%s",
                        quiz_id, concept_id, stage_for_log, fallback_id, attempts, type(generation_error).__name__,
                    )
            quiz.questions = questions
            quiz.status = QuizSetStatus.COMPLETED.value
            await session.commit()
        except Exception as exc:
            await session.rollback()
            failed = await session.get(QuizSet, quiz_id)
            if failed is None:
                logger.error(
                    "퀴즈 생성 실패(상태 저장 불가) quiz_set_id=%s concept_id=%s stage_id=%s source=%s attempts=%s elapsed_ms=%d",
                    quiz_id, concept_id, stage_for_log, source, attempts, _elapsed_ms(started),
                )
                raise QuizGenerationError(
                    quiz_set_id=quiz_id,
                    concept_id=concept_id,
                    message="퀴즈를 생성하지 못했습니다. 개념은 미통과(in_progress) 상태입니다.",
                ) from exc
            failed.questions = []
            failed.status = QuizSetStatus.FAILED.value
            await session.commit()
            logger.exception(
                "퀴즈 생성 실패 quiz_set_id=%s concept_id=%s stage_id=%s source=%s attempts=%s elapsed_ms=%d",
                quiz_id, concept_id, stage_for_log, source, attempts, _elapsed_ms(started),
            )
            await _notify_generation_failed(session_id, user_id=user_id)
            return _created_quiz(failed)

        logger.info(
            "퀴즈 생성 완료 quiz_set_id=%s concept_id=%s stage_id=%s source=%s attempts=%s elapsed_ms=%d",
            quiz_id, concept_id, stage_for_log, source, attempts, _elapsed_ms(started),
        )
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

        first = await self._submission_for_quiz(session, user_id, quiz_set_id)
        if first is not None:
            await _notify_quiz_result(quiz, first)
            return _submit_response(quiz, first)

        started = time.perf_counter()
        # Reject unsupported legacy content before saving a new result.
        for question in quiz.questions or []:
            _public_question(question)
            _quiz_display_text(question["explanation"])
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
            if raced is not None and raced.quiz_set_id != quiz_set_id:
                raise idempotency_conflict()
            if raced is None:
                raced = await self._submission_for_quiz(session, user_id, quiz_set_id)
            if raced is None:
                raise
            quiz = await self._owned_quiz(session, quiz_set_id, user_id)
            await _notify_quiz_result(quiz, raced)
            return _submit_response(quiz, raced)

        logger.info(
            "퀴즈 채점 완료 quiz_set_id=%s submission_id=%s correct_count=%s passed=%s elapsed_ms=%d",
            quiz_set_id, submission.id, correct_count, is_passed, _elapsed_ms(started),
        )
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

    async def _submission_for_quiz(self, session: AsyncSession, user_id: str, quiz_set_id: str) -> QuizSubmission | None:
        statement = select(QuizSubmission).where(
            QuizSubmission.user_id == user_id,
            QuizSubmission.quiz_set_id == quiz_set_id,
        ).order_by(QuizSubmission.created_at, QuizSubmission.id).limit(1)
        return (await session.execute(statement)).scalars().first()

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


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


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
                prompt=question_in_polite(_quiz_display_text(
                    question["prompt"], fallback="이 문항의 한국어 문제를 확인할 수 없습니다.",
                )),
                choices=[
                    QuizChoicePublic(
                        key=choice["key"],
                        text=choice["key"] if question["question_type"] == "ox" else choice_in_polite(
                            _quiz_display_text(
                                choice["text"], allow_numeric=True,
                                fallback="이 보기의 한국어 내용을 확인할 수 없습니다.",
                            )
                        ),
                    )
                    for choice in question["choices"]
                ],
                submitted_answer=answers.get(index) if submitted else None,
                is_correct=flags.get(index) if submitted else None,
                answer=question["answer"] if submitted else None,
                explanation=explanation_in_polite(_quiz_display_text(
                    question["explanation"], fallback="이 문항의 한국어 해설을 확인할 수 없습니다.",
                )) if submitted else None,
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
