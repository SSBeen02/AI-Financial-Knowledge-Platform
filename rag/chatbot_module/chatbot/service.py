"""세션·상태 조회.

재학습은 in_progress 개념의 최신 퀴즈 상태가 failed일 때만 연다.
최신 상태가 pending이거나, passed인데 개념 상태가 아직 in_progress이면 quiz_pending이다.
quiz_pending에서는 진행 중인 세션이 있을 수 없다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

from chatbot.concepts import (
    STATUS_IN_PROGRESS,
    STATUS_PASSED,
    STATUS_NOT_STARTED,
    ConceptRef,
    ConceptStatusReader,
    InProgressConceptView,
    StageCatalog,
    find_concept,
    lock_presentation,
    recommend_concepts,
)
from chatbot.config import AnswerKnowledgeMode, Settings
from chatbot.integrations import ConceptStatusService
from chatbot.llm import LLMAdapter, LLMError
from chatbot.prompts import HistoryTurn, Prompt, build_answer_prompt
from chatbot.relevance import (
    detect_concept,
    is_question_related,
    mentioned_concepts,
    normalize_term,
)
from chatbot.retrieval import ConceptCache, RetrievalResult, RetrievedDoc, Retriever, to_source_out
from chatbot.schemas import (
    ChatMode,
    ConceptStateOut,
    ConceptsResponse,
    ContextSourceOut,
    CurrentStageProgressOut,
    LearningConceptOut,
    LearningContextListItem,
    LearningCompletionOut,
    LearningContextOut,
    LearningTurnOut,
    MessageIn,
    MessageListItem,
    MessageResponse,
    MentionedConceptOut,
    ProgressResponse,
    QuizResultOut,
    QuizRetryOut,
    QuizSetOut,
    SessionOut,
    SourceOut,
    StageProgressOut,
    StateResponse,
    SuggestedConceptOut,
)
from chatbot.store import ChatStore, LatestQuiz, MessageRecord, SessionRecord
from chatbot.quiz import QuizService, QuizServiceError
from chatbot.tone import (
    active_learning_notice,
    ChatTone,
    excluded_concept_notice,
    extra_concept_notice,
    low_band_notice,
    learning_guide,
    no_active_session_complete_hint,
    other_stage_notice,
    passed_concept_notice,
    suggested_concept_notice,
    with_korean_particle,
)


class SessionNotFound(Exception):
    """없는 세션이거나 다른 사용자의 세션일 때."""


class ScreenInvariantError(Exception):
    """화면 모드와 세션 상태가 함께 있을 수 없을 때."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class MessageConflictError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ExternalServiceError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class MessageInvariantError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class LearningCompletionError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class QuizResultConflictError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class Screen:
    mode: ChatMode
    concept: ConceptRef | None
    active_session: SessionRecord | None


@dataclass(frozen=True)
class MessagePlan:
    concept: ConceptRef | None
    session: SessionRecord | None
    start_type: str | None
    attempt: int | None


@dataclass(frozen=True)
class PreparedMessage:
    user_id: str
    request: MessageIn
    plan: MessagePlan
    retrieval: RetrievalResult
    is_related: bool
    notice: str | None
    suggested_concept: SuggestedConceptOut | None
    prompt: Prompt
    started_at: float
    display_source_min_score: float
    chat_tone: ChatTone
    answer_knowledge_mode: AnswerKnowledgeMode


def list_concept_page(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    store: ChatStore,
    user_id: str,
    *,
    offset: int,
    limit: int,
    chat_tone: ChatTone = "hao",
) -> ConceptsResponse:
    screen = resolve_screen(catalog, status_service, store, user_id)
    response = recommend_concepts(
        catalog,
        status_service,
        user_id,
        offset=offset,
        limit=limit,
        screen_mode=screen.mode,
        locked_concept=screen.concept,
        chat_tone=chat_tone,
    )
    if screen.mode == "normal" and screen.concept is not None:
        response.locked_concept = _concept_out(screen.concept)
        response.notice = active_learning_notice(screen.concept.term, chat_tone)
    return response


def get_chat_state(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    store: ChatStore,
    user_id: str,
    chat_tone: ChatTone = "hao",
) -> StateResponse:
    screen = resolve_screen(catalog, status_service, store, user_id)
    _mode, locked, notice, _suggested = lock_presentation(
        screen.mode,
        screen.concept,
        chat_tone=chat_tone,
    )
    active = screen.active_session
    if screen.mode == "normal" and screen.concept is not None:
        locked = _concept_out(screen.concept)
        notice = active_learning_notice(screen.concept.term, chat_tone)
    return StateResponse(
        mode=screen.mode,
        active_session=_session_out(active) if active is not None else None,
        locked_concept=locked,
        notice=notice,
        complete_hint=(
            no_active_session_complete_hint(chat_tone) if active is None else None
        ),
        learning_guide=learning_guide(chat_tone),
        status_labels={
            "not_started": "미학습",
            "in_progress": "학습중",
            "passed": "통과",
        },
        progress=get_progress(catalog, status_service, user_id).current,
        quick_prompts=_quick_prompts(screen),
    )


def get_progress(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    user_id: str,
) -> ProgressResponse:
    """Return per-stage progress calculated only from concept statuses."""

    current_stage = status_service.get_current_stage(user_id)
    ordered_ids = tuple(catalog.stages)
    current_index = ordered_ids.index(current_stage)
    stages: list[StageProgressOut] = []
    current: CurrentStageProgressOut | None = None
    for index, stage_id in enumerate(ordered_ids):
        stage = catalog.stages[stage_id]
        statuses = status_service.get_statuses(user_id, stage_id)
        total = len(stage.concepts)
        passed = sum(
            statuses.get(concept.concept_id, STATUS_NOT_STARTED) == STATUS_PASSED
            for concept in stage.concepts
        )
        in_progress = sum(
            statuses.get(concept.concept_id, STATUS_NOT_STARTED) == STATUS_IN_PROGRESS
            for concept in stage.concepts
        )
        not_started = total - passed - in_progress
        summary = CurrentStageProgressOut(
            stage_id=stage.id,
            name_ko=stage.name_ko,
            total_count=total,
            passed_count=passed,
            in_progress_count=in_progress,
            not_started_count=not_started,
            remaining_count=total - passed,
            percent=(passed * 100) // total if total else 0,
        )
        if stage_id == current_stage:
            current = summary
        stages.append(
            StageProgressOut(
                **summary.model_dump(),
                unlocked=index <= current_index,
                completed=passed == total,
            )
        )
    if current is None:
        raise MessageInvariantError(f"알 수 없는 현재 스테이지입니다: {current_stage}")
    return ProgressResponse(current=current, stages=stages)


def get_user_session(store: ChatStore, user_id: str, session_id: str) -> SessionOut:
    record = store.get_session(user_id, session_id)
    if record is None:
        raise SessionNotFound()
    return _session_out(record)


def get_session_message_history(
    store: ChatStore,
    settings: Settings,
    user_id: str,
    session_id: str,
) -> list[MessageListItem]:
    if store.get_session(user_id, session_id) is None:
        raise SessionNotFound()
    return [
        _message_list_item(message, settings.display_source_min_score)
        for message in store.get_session_messages(user_id, session_id)
    ]


def get_message_history(
    store: ChatStore,
    settings: Settings,
    user_id: str,
    *,
    limit: int,
) -> list[MessageListItem]:
    return [
        _message_list_item(message, settings.display_source_min_score)
        for message in store.get_recent_messages(user_id, limit=limit)
    ]


def send_message(
    *,
    catalog: StageCatalog,
    status_service: ConceptStatusService,
    store: ChatStore,
    cache: ConceptCache,
    retriever: Retriever,
    llm: LLMAdapter,
    settings: Settings,
    user_id: str,
    request: MessageIn,
) -> MessageResponse:
    """POST /learning/messages의 전체 분기를 처리한다."""
    prepared = prepare_message(
        catalog=catalog,
        status_service=status_service,
        store=store,
        cache=cache,
        retriever=retriever,
        llm=llm,
        settings=settings,
        user_id=user_id,
        request=request,
    )
    try:
        raw_answer = llm.generate(prepared.prompt)
    except LLMError as exc:
        raise ExternalServiceError(exc.detail) from exc
    answer = _ensure_answer_suffixes(
        raw_answer,
        prepared.retrieval,
        prepared.answer_knowledge_mode,
    )
    return _persist_prepared_message(
        prepared=prepared,
        answer=answer,
        status_service=status_service,
        store=store,
    )


def prepare_message(
    *,
    catalog: StageCatalog,
    status_service: ConceptStatusService,
    store: ChatStore,
    cache: ConceptCache,
    retriever: Retriever,
    llm: LLMAdapter,
    settings: Settings,
    user_id: str,
    request: MessageIn,
) -> PreparedMessage:
    """비스트리밍과 SSE가 공유하는 분기·검색·검증·프롬프트 준비."""
    started_at = perf_counter()
    screen = resolve_screen(catalog, status_service, store, user_id)
    plan = _initial_message_plan(catalog, status_service, store, user_id, request, screen)

    try:
        retrieval = retriever.search(request.message)
    except Exception as exc:
        raise ExternalServiceError("검색 서비스 호출에 실패했습니다.") from exc

    suggested_concept: SuggestedConceptOut | None = None
    if plan.concept is None and plan.start_type is None and screen.mode == "normal":
        detected = _detect_for_current_stage(
            catalog, status_service, cache, settings, user_id, request.message, retrieval
        )
        if detected is not None:
            if settings.free_question_auto_start:
                plan = MessagePlan(
                    concept=detected,
                    session=None,
                    start_type="detected",
                    attempt=store.get_next_attempt(
                        user_id, detected.concept_id, detected.stage_id
                    ),
                )
            else:
                suggested_concept = SuggestedConceptOut(
                    concept_id=detected.concept_id,
                    term=detected.term,
                )

    cached = _cached_concept(cache, plan.concept) if plan.concept is not None else None
    history = _message_history(store, user_id, plan.session)
    previous_attempt_history = _previous_attempt_history(store, user_id, plan)
    is_related = _related_for_plan(
        question=request.message,
        plan=plan,
        cached=cached,
        cache=cache,
        retrieval=retrieval,
        llm=llm,
        history=history,
    )
    notice = _message_notice(
        catalog=catalog,
        status_service=status_service,
        cache=cache,
        user_id=user_id,
        question=request.message,
        retrieval=retrieval,
        chat_tone=settings.chat_tone,
    )
    if suggested_concept is not None:
        notice = suggested_concept_notice(suggested_concept.term, settings.chat_tone)
    prompt = build_answer_prompt(
        question=request.message,
        current_concept=cached,
        band=retrieval.band,
        sources=retrieval.sources,
        history=history,
        previous_attempt_history=previous_attempt_history,
        stage=plan.concept.stage_id if plan.concept is not None else None,
        attempt=plan.attempt,
        chat_tone=settings.chat_tone,
        knowledge_mode=settings.answer_knowledge_mode,
        chat_emoji=settings.chat_emoji,
    )
    return PreparedMessage(
        user_id=user_id,
        request=request,
        plan=plan,
        retrieval=retrieval,
        is_related=is_related,
        notice=notice,
        suggested_concept=suggested_concept,
        prompt=prompt,
        started_at=started_at,
        display_source_min_score=settings.display_source_min_score,
        chat_tone=settings.chat_tone,
        answer_knowledge_mode=settings.answer_knowledge_mode,
    )


async def stream_message_events(
    *,
    prepared: PreparedMessage,
    status_service: ConceptStatusService,
    store: ChatStore,
    llm: LLMAdapter,
    is_disconnected: Callable[[], Awaitable[bool]],
    request_id: str,
) -> AsyncIterator[str]:
    """답변을 SSE로 보내고, 완주 및 연결 유지가 확인된 뒤에만 상태를 반영한다."""
    chunks: list[str] = []
    iterator: Iterator[str] | None = None
    try:
        iterator = iter(llm.stream(prepared.prompt))
        while True:
            if await is_disconnected():
                return
            chunk = await asyncio.to_thread(_next_or_end, iterator)
            if chunk is _STREAM_END:
                break
            text = str(chunk)
            if not text:
                continue
            chunks.append(text)
            yield _sse("token", {"delta": text})

        raw_answer = "".join(chunks).strip()
        if not raw_answer:
            raise LLMError("LLM이 비어 있는 응답을 반환했습니다.")
        answer = _ensure_answer_suffixes(
            raw_answer,
            prepared.retrieval,
            prepared.answer_knowledge_mode,
        )
        suffix = answer[len(raw_answer) :]
        if suffix:
            if await is_disconnected():
                return
            yield _sse("token", {"delta": suffix})

        # 마지막 토큰 전송 뒤 취소 신호가 처리될 기회를 주고, 커밋 직전에 다시 확인한다.
        await asyncio.sleep(0)
        if await is_disconnected():
            return
        response = _persist_prepared_message(
            prepared=prepared,
            answer=answer,
            status_service=status_service,
            store=store,
        )
        metadata = response.model_dump(mode="json", exclude={"answer"})
        yield _sse("done", metadata)
    except LLMError as exc:
        if not await is_disconnected():
            yield _sse(
                "error",
                {
                    "code": "external_service_error",
                    "message": exc.detail,
                    "request_id": request_id,
                },
            )
    except asyncio.CancelledError:
        raise
    finally:
        if iterator is not None:
            with suppress(Exception):
                iterator.close()  # type: ignore[attr-defined]


def _persist_prepared_message(
    *,
    prepared: PreparedMessage,
    answer: str,
    status_service: ConceptStatusService,
    store: ChatStore,
) -> MessageResponse:
    latency_ms = max(0, round((perf_counter() - prepared.started_at) * 1000))

    plan = prepared.plan
    retrieval = prepared.retrieval
    session = plan.session
    session_started = False
    if plan.start_type is not None and plan.concept is not None:
        if plan.start_type in {"keyword", "detected"}:
            status_service.mark_in_progress(
                prepared.user_id,
                plan.concept.concept_id,
                plan.concept.stage_id,
            )
        session = store.create_session(
            user_id=prepared.user_id,
            stage=plan.concept.stage_id,
            concept_id=plan.concept.concept_id,
            term=plan.concept.term,
            attempt=plan.attempt or 1,
            start_type=plan.start_type,  # type: ignore[arg-type]
        )
        session_started = True

    source_models = [to_source_out(source) for source in retrieval.sources]
    display_source_models = [
        to_source_out(source)
        for source in _display_sources(
            retrieval,
            current_concept_id=session.concept_id if session is not None else None,
            minimum_score=prepared.display_source_min_score,
        )
    ]
    pair = store.save_message_pair(
        user_id=prepared.user_id,
        session_id=session.session_id if session is not None else None,
        question=prepared.request.message,
        answer=answer,
        is_related=prepared.is_related,
        band=retrieval.band,
        top_score=retrieval.top_score,
        sources=[source.model_dump() for source in source_models],
        display_sources=[source.model_dump() for source in display_source_models],
        latency_ms=latency_ms,
    )
    concept_state = None
    if session is not None:
        concept_state = ConceptStateOut(
            concept_id=session.concept_id,
            term=session.term,
            stage_id=session.stage,  # type: ignore[arg-type]
            status=STATUS_IN_PROGRESS,
            attempt=session.attempt,
        )
    return MessageResponse(
        answer=answer,
        session_id=session.session_id if session is not None else None,
        session_started=session_started,
        concept=concept_state,
        is_related=prepared.is_related,
        band=retrieval.band,
        top_score=retrieval.top_score,
        sources=source_models,
        display_sources=display_source_models,
        message_id=pair.assistant.message_id,
        notice=prepared.notice,
        suggested_concept=prepared.suggested_concept,
    )


_STREAM_END = object()


def _next_or_end(iterator: Iterator[str]) -> str | object:
    try:
        return next(iterator)
    except StopIteration:
        return _STREAM_END


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def complete_learning_session(
    *,
    status_service: ConceptStatusService,
    store: ChatStore,
    cache: ConceptCache,
    quiz_service: QuizService,
    user_id: str,
    session_id: str,
    idempotency_key: str,
) -> LearningCompletionOut:
    replay = store.get_completion_request(user_id, idempotency_key)
    if replay is not None:
        if replay.session_id != session_id:
            raise LearningCompletionError(
                "같은 Idempotency-Key를 다른 학습 완료 요청에 사용할 수 없습니다.",
                status_code=409,
            )
        return LearningCompletionOut.model_validate(replay.payload)

    session = store.get_session(user_id, session_id)
    if session is None:
        raise SessionNotFound()
    if session.status != "active":
        raise LearningCompletionError("이미 완료된 세션입니다.", status_code=409)
    if store.get_pending_quiz(user_id) is not None:
        raise LearningCompletionError(
            "퀴즈 결과를 기다리는 학습 맥락이 있습니다.", status_code=409
        )

    messages = store.get_session_messages(user_id, session_id)
    turns = _learning_turns(messages)
    if not any(turn.is_related for turn in turns):
        raise LearningCompletionError("학습 완료에는 관련 대화가 최소 1턴 필요합니다.")

    cached = cache.get(session.concept_id)
    if cached is None:
        raise MessageInvariantError(f"개념 캐시에 문서가 없습니다: {session.concept_id}")
    mentions = _session_mentions(messages, cache, current_concept_id=session.concept_id)
    status = status_service.get_statuses(user_id, session.stage).get(session.concept_id, STATUS_IN_PROGRESS)
    completed_at = datetime.now(timezone.utc)
    context = LearningContextOut(
        session_id=session.session_id,
        user_id=user_id,
        status="completed",
        quiz_status="pending",
        concept=LearningConceptOut(
            concept_id=session.concept_id,
            term=session.term,
            stage_id=session.stage,  # type: ignore[arg-type]
            status=status,  # type: ignore[arg-type]
            attempt=session.attempt,
            definition=_definition_from_text(cached.text),
        ),
        turns=turns,
        mentioned_concepts=mentions,
        reference_chunk_ids=_reference_chunk_ids(turns),
        completed_at=completed_at,
    )
    context_payload = context.model_dump(mode="json")
    try:
        quiz_result = quiz_service.create_quiz_set(
            user_id=user_id,
            session_id=session.session_id,
            concept_id=session.concept_id,
            stage_id=session.stage,
            learning_context=context_payload,
            reference_chunk_ids=context.reference_chunk_ids,
        )
    except QuizServiceError as exc:
        raise ExternalServiceError("퀴즈 생성 요청에 실패했습니다.") from exc
    quiz = QuizSetOut(
        quiz_set_id=quiz_result.quiz_set_id,
        status=quiz_result.status,
    )
    if quiz.status == "failed":
        context.quiz_status = "generation_failed"
        context_payload = context.model_dump(mode="json")
    completion = LearningCompletionOut(
        **context.model_dump(),
        quiz=quiz,
    )
    record = store.complete_session_with_context(
        session_id=session.session_id,
        user_id=user_id,
        concept_id=session.concept_id,
        idempotency_key=idempotency_key,
        payload=context_payload,
        completion_payload=completion.model_dump(mode="json"),
        quiz_status=context.quiz_status,
        completed_at=completed_at,
    )
    del record
    return completion


def report_quiz_generation_failed(
    *, store: ChatStore, user_id: str, session_id: str
) -> LearningContextOut:
    """퀴즈 모듈의 실패 콜백을 세션당 한 번만 반영한다."""
    session = store.get_session(user_id, session_id)
    if session is None:
        raise SessionNotFound()
    record = store.get_learning_context(user_id, session_id)
    if record is None:
        raise QuizResultConflictError("완료된 세션의 학습 맥락을 찾을 수 없습니다.")
    if record.quiz_status == "pending":
        store.set_quiz_status(user_id, session_id, "generation_failed")
    return get_learning_context(store, user_id, session_id)


def retry_quiz_generation(
    *,
    status_service: ConceptStatusService,
    store: ChatStore,
    quiz_service: QuizService,
    user_id: str,
    session_id: str,
    idempotency_key: str,
) -> QuizRetryOut:
    get_retry = getattr(status_service, "get_quiz_retry_request", None)
    save_retry = getattr(status_service, "save_quiz_retry_request", None)
    if get_retry is None or save_retry is None:
        raise MessageInvariantError("학습 관리 서비스가 퀴즈 재요청 멱등 처리를 지원하지 않습니다.")
    replay = get_retry(user_id, session_id, idempotency_key)
    if replay is not None:
        return QuizRetryOut.model_validate(replay)
    original = store.get_session(user_id, session_id)
    context_record = store.get_learning_context(user_id, session_id)
    if original is None or context_record is None:
        raise SessionNotFound()
    if context_record.quiz_status != "generation_failed":
        raise QuizResultConflictError("퀴즈 생성에 실패한 세션만 다시 요청할 수 있습니다.")
    retry = store.create_session(
        user_id=user_id,
        stage=original.stage,
        concept_id=original.concept_id,
        term=original.term,
        attempt=original.attempt,
        start_type="quiz_retry",
        status="completed",
        completed_at=datetime.now(timezone.utc),
    )
    retry_context = dict(context_record.payload)
    retry_context["session_id"] = retry.session_id
    retry_context["quiz_status"] = "pending"
    store.save_learning_context(
        session_id=retry.session_id,
        user_id=user_id,
        concept_id=retry.concept_id,
        payload=retry_context,
        quiz_status="pending",
    )
    reference_chunk_ids = list(retry_context.get("reference_chunk_ids") or [])
    try:
        quiz_result = quiz_service.create_quiz_set(
            user_id=user_id,
            session_id=retry.session_id,
            concept_id=retry.concept_id,
            stage_id=retry.stage,
            learning_context=retry_context,
            reference_chunk_ids=reference_chunk_ids,
        )
    except QuizServiceError as exc:
        store.set_quiz_status(user_id, retry.session_id, "generation_failed")
        raise ExternalServiceError("퀴즈 재요청에 실패했습니다.") from exc
    if quiz_result.status == "failed":
        store.set_quiz_status(user_id, retry.session_id, "generation_failed")
    response = QuizRetryOut(
        session_id=retry.session_id,
        original_session_id=session_id,
        concept_id=retry.concept_id,
        stage_id=retry.stage,  # type: ignore[arg-type]
        attempt=retry.attempt,
        quiz=QuizSetOut(
            quiz_set_id=quiz_result.quiz_set_id,
            status=quiz_result.status,
        ),
    )
    saved = save_retry(
        user_id=user_id,
        original_session_id=session_id,
        retry_session_id=retry.session_id,
        idempotency_key=idempotency_key,
        response_payload=response.model_dump(mode="json"),
    )
    return QuizRetryOut.model_validate(saved)


def get_learning_context(
    store: ChatStore,
    user_id: str,
    session_id: str,
) -> LearningContextOut:
    record = store.get_learning_context(user_id, session_id)
    if record is None:
        raise SessionNotFound()
    payload = dict(record.payload)
    payload["quiz_status"] = record.quiz_status
    return LearningContextOut.model_validate(payload)


def list_learning_contexts(
    store: ChatStore,
    user_id: str,
) -> list[LearningContextListItem]:
    result: list[LearningContextListItem] = []
    for record in store.list_learning_contexts(user_id):
        context = dict(record.payload)
        concept = context.get("concept") or {}
        result.append(
            LearningContextListItem(
                session_id=record.session_id,
                concept_id=record.concept_id,
                term=str(concept.get("term") or ""),
                status="completed",
                quiz_status=record.quiz_status,
                completed_at=context.get("completed_at"),
            )
        )
    return result


def report_quiz_result(
    *,
    status_service: ConceptStatusService,
    store: ChatStore,
    user_id: str,
    session_id: str,
    submission_id: str,
    concept_id: str,
    stage_id: str,
    correct_count: int,
    passed: bool,
) -> QuizResultOut:
    session = store.get_session(user_id, session_id)
    if session is None:
        raise SessionNotFound()
    result = status_service.apply_quiz_result(
        user_id=user_id,
        submission_id=submission_id,
        session_id=session_id,
        concept_id=concept_id,
        stage_id=stage_id,
        correct_count=correct_count,
        passed=passed,
    )
    return QuizResultOut.model_validate(result)


def _learning_turns(messages: list[MessageRecord]) -> list[LearningTurnOut]:
    turns: list[LearningTurnOut] = []
    question: MessageRecord | None = None
    for message in messages:
        if message.role == "user":
            question = message
            continue
        if message.role != "assistant" or question is None:
            continue
        sources = [
            ContextSourceOut(
                concept_id=str(source.get("concept_id") or ""),
                collection=str(source.get("collection") or ""),
                label=str(source.get("label") or ""),
                images=source.get("images") if isinstance(source.get("images"), list) else None,
            )
            for source in (message.sources or [])
        ]
        turns.append(
            LearningTurnOut(
                question=question.content,
                answer=message.content,
                is_related=message.is_related is True,
                sources=sources,
                created_at=question.created_at,
            )
        )
        question = None
    return turns


def _reference_chunk_ids(turns: list[LearningTurnOut]) -> list[str]:
    """퀴즈 연동용 근거 청크 ID를 대화 순서대로 중복 제거한다."""
    seen: set[str] = set()
    result: list[str] = []
    for turn in turns:
        for source in turn.sources:
            chunk_id = source.concept_id
            if chunk_id and chunk_id not in seen:
                seen.add(chunk_id)
                result.append(chunk_id)
    return result


def _session_mentions(
    messages: list[MessageRecord],
    cache: ConceptCache,
    *,
    current_concept_id: str,
) -> list[MentionedConceptOut]:
    found: dict[str, MentionedConceptOut] = {}
    question: MessageRecord | None = None
    for message in messages:
        if message.role == "user":
            question = message
            continue
        if message.role != "assistant" or question is None:
            continue
        for concept in mentioned_concepts(
            question.content,
            cache.values(),
            exclude_concept_id=current_concept_id,
        ):
            found.setdefault(
                concept.concept_id,
                MentionedConceptOut(concept_id=concept.concept_id, term=concept.term),
            )
        question = None
    return list(found.values())


def _definition_from_text(text: str) -> str:
    marker = "설명:"
    if marker not in text:
        return text.strip()
    return text.split(marker, 1)[1].strip()


def _display_sources(
    retrieval: RetrievalResult,
    *,
    current_concept_id: str | None,
    minimum_score: float,
) -> list[RetrievedDoc]:
    """화면용 출처만 고른다. LLM 근거 및 저장용 sources에는 영향이 없다."""
    if retrieval.band == "low":
        return []

    candidates = list(retrieval.sources)
    if current_concept_id is not None and not any(
        source.concept_id == current_concept_id for source in candidates
    ):
        current_hit = next(
            (hit for hit in retrieval.concept_hits if hit.concept_id == current_concept_id),
            None,
        )
        if current_hit is not None:
            candidates.insert(0, current_hit)

    selected: list[RetrievedDoc] = []
    seen: set[tuple[str, str]] = set()
    for source in candidates:
        key = (source.collection, source.concept_id)
        if key in seen:
            continue
        if source.concept_id == current_concept_id or source.score >= minimum_score:
            selected.append(source)
            seen.add(key)
    return selected


def resolve_screen(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    store: ChatStore,
    user_id: str,
) -> Screen:
    stage = status_service.get_current_stage(user_id)
    in_progress = status_service.get_in_progress_concept(user_id, stage)
    latest = (
        store.get_latest_quiz(user_id, in_progress.concept_id, in_progress.stage)
        if in_progress is not None
        else None
    )
    mode, concept = _mode_for(catalog, in_progress, latest)
    active = store.get_active_session(user_id)
    if mode in ("quiz_pending", "quiz_generation_failed") and active is not None:
        raise ScreenInvariantError("퀴즈 대기 중에는 진행 중인 세션이 있을 수 없습니다.")
    return Screen(mode=mode, concept=concept, active_session=active)


def _initial_message_plan(
    catalog: StageCatalog,
    status_service: ConceptStatusService,
    store: ChatStore,
    user_id: str,
    request: MessageIn,
    screen: Screen,
) -> MessagePlan:
    if screen.active_session is not None:
        active = screen.active_session
        concept = find_concept(catalog, active.concept_id, active.stage)
        return MessagePlan(concept, active, None, active.attempt)
    if screen.mode in ("quiz_pending", "quiz_generation_failed"):
        return MessagePlan(None, None, None, None)
    if screen.mode == "relearn":
        if screen.concept is None:
            raise MessageInvariantError("재학습 개념을 찾을 수 없습니다.")
        if request.concept_id is None:
            return MessagePlan(None, None, None, None)
        if request.concept_id != screen.concept.concept_id:
            raise MessageConflictError("학습 중인 개념을 먼저 통과해야 합니다.")
        return MessagePlan(
            screen.concept,
            None,
            "relearn",
            store.get_next_attempt(
                user_id, screen.concept.concept_id, screen.concept.stage_id
            ),
        )
    if request.concept_id is not None:
        stage_id = status_service.get_current_stage(user_id)
        try:
            concept = find_concept(catalog, request.concept_id, stage_id)
        except Exception as exc:
            raise MessageConflictError("선택한 개념을 해당 스테이지에서 찾을 수 없습니다.") from exc
        statuses = status_service.get_statuses(user_id, stage_id)
        if statuses.get(concept.concept_id, STATUS_NOT_STARTED) != STATUS_NOT_STARTED:
            raise MessageConflictError("현재 선택할 수 있는 학습 대상 개념이 아닙니다.")
        return MessagePlan(
            concept,
            None,
            "keyword",
            store.get_next_attempt(user_id, concept.concept_id, stage_id),
        )
    return MessagePlan(None, None, None, None)


def _detect_for_current_stage(
    catalog: StageCatalog,
    status_service: ConceptStatusService,
    cache: ConceptCache,
    settings: Settings,
    user_id: str,
    question: str,
    retrieval: RetrievalResult,
) -> ConceptRef | None:
    stage_id = status_service.get_current_stage(user_id)
    stage = catalog.stages.get(stage_id)
    if stage is None:
        raise MessageInvariantError(f"현재 스테이지를 찾을 수 없습니다: {stage_id}")
    statuses = status_service.get_statuses(user_id, stage_id)
    candidates = [
        concept
        for concept in stage.concepts
        if statuses.get(concept.concept_id, STATUS_NOT_STARTED) == STATUS_NOT_STARTED
    ]
    return detect_concept(
        question=question,
        candidates=candidates,
        cache=cache,
        retrieval=retrieval,
        band_high=settings.band_high,
    )


def _cached_concept(cache: ConceptCache, concept: ConceptRef):
    cached = cache.get(concept.concept_id)
    if cached is None:
        raise MessageInvariantError(f"개념 캐시에 문서가 없습니다: {concept.concept_id}")
    return cached


def _message_history(
    store: ChatStore,
    user_id: str,
    session: SessionRecord | None,
) -> list[HistoryTurn]:
    if session is None:
        return []
    return [
        HistoryTurn(question=turn.question, answer=turn.answer)
        for turn in store.get_recent_turns(user_id, session.session_id, limit=6)
    ]


def _previous_attempt_history(
    store: ChatStore,
    user_id: str,
    plan: MessagePlan,
) -> list[HistoryTurn]:
    if plan.concept is None or plan.attempt is None or plan.attempt < 2:
        return []
    return [
        HistoryTurn(question=turn.question, answer=turn.answer)
        for turn in store.get_previous_attempt_turns(
            user_id,
            plan.concept.concept_id,
            plan.concept.stage_id,
            before_attempt=plan.attempt,
            limit=4,
        )
    ]


def _related_for_plan(
    *,
    question: str,
    plan: MessagePlan,
    cached,
    cache: ConceptCache,
    retrieval: RetrievalResult,
    llm: LLMAdapter,
    history: list[HistoryTurn],
) -> bool:
    if plan.concept is None or cached is None:
        return False
    return is_question_related(
        question=question,
        current=cached,
        cache=cache,
        retrieval=retrieval,
        llm=llm,
        history=history,
        force_true=plan.start_type in {"keyword", "detected"},
    )


def _message_notice(
    *,
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    cache: ConceptCache,
    user_id: str,
    question: str,
    retrieval: RetrievalResult,
    chat_tone: ChatTone,
) -> str | None:
    """Build deterministic UI guidance without asking the LLM to phrase it."""

    top = retrieval.concept_hits[0] if retrieval.concept_hits else None
    explicitly_mentioned = top is not None and _mentions_retrieved_doc(question, top)
    if explicitly_mentioned and top is not None:
        stage_tags = set(top.stages)
        if "excluded" in stage_tags:
            return excluded_concept_notice(top.term, chat_tone)
        if "extra" in stage_tags:
            return extra_concept_notice(top.term, chat_tone)

    normalized_question = normalize_term(question)
    rank = {hit.concept_id: index for index, hit in enumerate(retrieval.concept_hits)}
    mentioned_learning = [
        concept
        for concept in cache.values()
        if any(
            normalized_term and normalized_term in normalized_question
            for term in (concept.term, *concept.aliases)
            if (normalized_term := normalize_term(term))
        )
    ]
    mentioned_learning.sort(key=lambda concept: rank.get(concept.concept_id, len(rank)))
    learning_doc = mentioned_learning[0] if mentioned_learning else None
    if learning_doc is None and explicitly_mentioned and top is not None and top.concept_id in catalog.by_concept:
        learning_doc = top

    if learning_doc is not None:
        current_stage = status_service.get_current_stage(user_id)
        current_ref = next(
            (
                ref
                for ref in catalog.by_concept.get(learning_doc.concept_id, ())
                if ref.stage_id == current_stage
            ),
            None,
        )
        if current_ref is not None:
            current_status = status_service.get_statuses(user_id, current_stage).get(
                learning_doc.concept_id, STATUS_NOT_STARTED
            )
            if current_status == STATUS_PASSED:
                return passed_concept_notice(learning_doc.term, chat_tone)
        else:
            ordered = tuple(catalog.stages)
            current_index = ordered.index(current_stage)
            future_refs = sorted(
                (
                    ref
                    for ref in catalog.by_concept.get(learning_doc.concept_id, ())
                    if ordered.index(ref.stage_id) > current_index
                    and status_service.get_statuses(user_id, ref.stage_id).get(
                        ref.concept_id, STATUS_NOT_STARTED
                    )
                    != STATUS_PASSED
                ),
                key=lambda ref: ordered.index(ref.stage_id),
            )
            if future_refs:
                target = future_refs[0]
                return other_stage_notice(
                    learning_doc.term,
                    catalog.stages[current_stage].name_ko,
                    target.stage_name_ko,
                    chat_tone,
                )
            prior_refs = catalog.by_concept.get(learning_doc.concept_id, ())
            if prior_refs and all(
                status_service.get_statuses(user_id, ref.stage_id).get(
                    ref.concept_id, STATUS_NOT_STARTED
                )
                == STATUS_PASSED
                for ref in prior_refs
            ):
                return passed_concept_notice(learning_doc.term, chat_tone)

    if retrieval.band == "low":
        return low_band_notice(chat_tone)
    return None


def _mentions_retrieved_doc(question: str, doc: RetrievedDoc) -> bool:
    normalized_question = normalize_term(question)
    return any(
        normalized_term and normalized_term in normalized_question
        for term in (doc.term, *doc.aliases)
        if (normalized_term := normalize_term(term))
    )


def _ensure_answer_suffixes(
    answer: str,
    retrieval: RetrievalResult,
    knowledge_mode: AnswerKnowledgeMode,
) -> str:
    result = answer.strip()
    labels = list(dict.fromkeys(source.label for source in retrieval.sources))
    if not labels or knowledge_mode == "free":
        return result
    prefix = "핵심 정의 출처:" if knowledge_mode == "dictionary_plus" else "출처:"
    if prefix not in result:
        result += f"\n\n{prefix} {', '.join(labels)}"
    return result


def _message_list_item(
    message: MessageRecord,
    minimum_score: float,
) -> MessageListItem:
    raw_sources = message.display_sources
    if raw_sources is None:
        raw_sources = [
            source
            for source in (message.sources or [])
            if message.band != "low" and float(source.get("score") or 0) >= minimum_score
        ]
    display_sources: list[SourceOut] = []
    for source in raw_sources:
        try:
            display_sources.append(SourceOut.model_validate(source))
        except (TypeError, ValueError):
            continue
    return MessageListItem(
        message_id=message.message_id,
        session_id=message.session_id,
        attempt=message.attempt,
        concept_id=message.concept_id,
        start_type=message.start_type,
        role=message.role,
        content=message.content,
        is_related=message.is_related,
        band=message.band,  # type: ignore[arg-type]
        display_sources=display_sources,
        created_at=message.created_at,
    )


def _mode_for(
    catalog: StageCatalog,
    in_progress: InProgressConceptView | None,
    latest: LatestQuiz | None,
) -> tuple[ChatMode, ConceptRef | None]:
    if in_progress is None or latest is None:
        if in_progress is None:
            return "normal", None
        return "normal", find_concept(catalog, in_progress.concept_id, in_progress.stage)
    concept = find_concept(catalog, in_progress.concept_id, in_progress.stage)
    if latest.quiz_status == "failed":
        return "relearn", concept
    if latest.quiz_status in ("pending", "passed"):
        return "quiz_pending", concept
    if latest.quiz_status == "generation_failed":
        return "quiz_generation_failed", concept
    return "normal", None


def _concept_out(concept: ConceptRef):
    from chatbot.schemas import ConceptOut

    return ConceptOut(
        concept_id=concept.concept_id,
        term=concept.term,
        term_full=concept.term_full,
        subcategory=concept.subcategory,
        order=concept.order,
    )


def _quick_prompts(screen: Screen) -> list[str]:
    if screen.concept is None or screen.mode in ("quiz_pending", "quiz_generation_failed"):
        return []
    term = screen.concept.term
    if screen.mode == "relearn":
        return [
            f"{term}에 대해 다시 알려줘",
            f"{term}의 다른 예시를 들어줘",
            f"{with_korean_particle(term, '와/과')} 비슷한 개념은 뭐야?",
        ]
    return [
        f"{term}에 대해 더 자세히 알려줘",
        f"{term}의 예시를 더 들어줘",
        f"{with_korean_particle(term, '와/과')} 비슷한 개념은 뭐야?",
    ]


def _session_out(record: SessionRecord) -> SessionOut:
    return SessionOut(
        session_id=record.session_id,
        stage_id=record.stage,  # type: ignore[arg-type]
        concept_id=record.concept_id,
        term=record.term,
        attempt=record.attempt,
        start_type=record.start_type,
        status=record.status,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )
