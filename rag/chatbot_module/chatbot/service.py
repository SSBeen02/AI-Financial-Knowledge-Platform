"""세션·상태 조회.

재학습은 미통과 개념의 최신 퀴즈 상태가 failed일 때만 연다.
최신 상태가 pending이거나, passed인데 개념 상태가 아직 미통과이면 quiz_pending이다.
quiz_pending에서는 진행 중인 세션이 있을 수 없다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass
from time import perf_counter

from chatbot.concepts import (
    STATUS_FAILED,
    STATUS_UNLEARNED,
    ConceptRef,
    ConceptStatusReader,
    FailedConceptView,
    StageCatalog,
    find_concept,
    lock_presentation,
    recommend_concepts,
)
from chatbot.config import Settings
from chatbot.integrations import ConceptStatusService
from chatbot.llm import LLMAdapter, LLMError
from chatbot.prompts import HistoryTurn, Prompt, build_answer_prompt
from chatbot.relevance import detect_concept, is_question_related, mentioned_concepts
from chatbot.retrieval import ConceptCache, RetrievalResult, RetrievedDoc, Retriever, to_source_out
from chatbot.schemas import (
    ChatMode,
    ConceptStateOut,
    ConceptsResponse,
    ContextSourceOut,
    LearningConceptOut,
    LearningContextListItem,
    LearningContextOut,
    LearningTurnOut,
    MessageIn,
    MessageResponse,
    MentionedConceptOut,
    SessionOut,
    StateResponse,
)
from chatbot.store import ChatStore, LatestQuiz, MessageRecord, SessionRecord


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
    mark_stage: str | None


@dataclass(frozen=True)
class PreparedMessage:
    user_id: str
    request: MessageIn
    plan: MessagePlan
    retrieval: RetrievalResult
    is_related: bool
    excluded_term: bool
    prompt: Prompt
    started_at: float
    display_source_min_score: float


def list_concept_page(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    store: ChatStore,
    user_id: str,
    *,
    offset: int,
    limit: int,
    stage: str | None,
) -> ConceptsResponse:
    screen = resolve_screen(catalog, status_service, store, user_id)
    return recommend_concepts(
        catalog,
        status_service,
        user_id,
        offset=offset,
        limit=limit,
        stage=stage,
        screen_mode=screen.mode,
        locked_concept=screen.concept,
    )


def get_chat_state(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    store: ChatStore,
    user_id: str,
) -> StateResponse:
    screen = resolve_screen(catalog, status_service, store, user_id)
    _mode, locked, notice, _suggested = lock_presentation(screen.mode, screen.concept)
    active = screen.active_session
    return StateResponse(
        mode=screen.mode,
        active_session=_session_out(active) if active is not None else None,
        locked_concept=locked,
        notice=notice,
    )


def get_user_session(store: ChatStore, user_id: str, session_id: str) -> SessionOut:
    record = store.get_session(user_id, session_id)
    if record is None:
        raise SessionNotFound()
    return _session_out(record)


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
    """POST /chat/messages의 전체 분기를 처리한다."""
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
        prepared.excluded_term,
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

    if plan.concept is None and plan.start_type is None and screen.mode == "normal":
        detected = _detect_for_current_stage(
            catalog, status_service, cache, settings, user_id, request.message, retrieval
        )
        if detected is not None:
            plan = MessagePlan(
                concept=detected,
                session=None,
                start_type="detected",
                attempt=store.get_next_attempt(user_id, detected.doc_id),
                mark_stage=None,
            )

    cached = _cached_concept(cache, plan.concept) if plan.concept is not None else None
    history = _message_history(store, user_id, plan.session)
    is_related = _related_for_plan(
        question=request.message,
        plan=plan,
        cached=cached,
        cache=cache,
        retrieval=retrieval,
        llm=llm,
    )
    excluded_term = bool(
        retrieval.concept_hits and retrieval.concept_hits[0].stages == ("excluded",)
    )
    prompt = build_answer_prompt(
        question=request.message,
        current_concept=cached,
        band=retrieval.band,
        sources=retrieval.sources,
        history=history,
        excluded_term=excluded_term,
    )
    return PreparedMessage(
        user_id=user_id,
        request=request,
        plan=plan,
        retrieval=retrieval,
        is_related=is_related,
        excluded_term=excluded_term,
        prompt=prompt,
        started_at=started_at,
        display_source_min_score=settings.display_source_min_score,
    )


async def stream_message_events(
    *,
    prepared: PreparedMessage,
    status_service: ConceptStatusService,
    store: ChatStore,
    llm: LLMAdapter,
    is_disconnected: Callable[[], Awaitable[bool]],
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
            prepared.excluded_term,
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
            yield _sse("error", {"detail": exc.detail})
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
            status_service.mark_failed(
                prepared.user_id,
                plan.concept.doc_id,
                stage=plan.mark_stage,
            )
        session = store.create_session(
            user_id=prepared.user_id,
            stage=plan.concept.stage_id,
            doc_id=plan.concept.doc_id,
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
            current_doc_id=session.doc_id if session is not None else None,
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
        latency_ms=latency_ms,
    )
    concept_state = None
    if session is not None:
        concept_state = ConceptStateOut(
            doc_id=session.doc_id,
            term=session.term,
            stage=session.stage,
            status=STATUS_FAILED,
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
    user_id: str,
    session_id: str,
) -> LearningContextOut:
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
    turns = _related_learning_turns(messages)
    if not turns:
        raise LearningCompletionError("학습 완료에는 관련 대화가 최소 1턴 필요합니다.")

    cached = cache.get(session.doc_id)
    if cached is None:
        raise MessageInvariantError(f"개념 캐시에 문서가 없습니다: {session.doc_id}")
    mentions = _session_mentions(messages, cache, current_doc_id=session.doc_id)
    completed = store.complete_session(user_id, session_id)
    status = status_service.get_statuses(user_id, session.stage).get(session.doc_id, STATUS_FAILED)
    context = LearningContextOut(
        session_id=session.session_id,
        user_id=user_id,
        status="completed",
        quiz_status="pending",
        concept=LearningConceptOut(
            doc_id=session.doc_id,
            term=session.term,
            stage=session.stage,
            status=status,  # type: ignore[arg-type]
            attempt=session.attempt,
            definition=_definition_from_text(cached.text),
        ),
        turns=turns,
        mentioned_concepts=mentions,
        completed_at=completed.completed_at,
    )
    store.save_learning_context(
        session_id=session.session_id,
        user_id=user_id,
        doc_id=session.doc_id,
        payload=context.model_dump(mode="json"),
        quiz_status="pending",
    )
    return context


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
                doc_id=record.doc_id,
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
    passed: bool,
) -> LearningContextOut:
    session = store.get_session(user_id, session_id)
    if session is None:
        raise SessionNotFound()
    if session.status != "completed":
        raise QuizResultConflictError("학습을 완료한 세션에만 퀴즈 결과를 기록할 수 있습니다.")
    record = store.get_learning_context(user_id, session_id)
    if record is None:
        raise QuizResultConflictError("완료된 세션의 학습 맥락을 찾을 수 없습니다.")
    if record.quiz_status != "pending":
        raise QuizResultConflictError("이미 퀴즈 결과가 기록된 세션입니다.")
    store.set_quiz_status(user_id, session_id, "passed" if passed else "failed")
    status_service.note_quiz_result(user_id, record.doc_id, passed)
    return get_learning_context(store, user_id, session_id)


def _related_learning_turns(messages: list[MessageRecord]) -> list[LearningTurnOut]:
    turns: list[LearningTurnOut] = []
    question: MessageRecord | None = None
    for message in messages:
        if message.role == "user":
            question = message
            continue
        if message.role != "assistant" or question is None:
            continue
        if message.is_related is True:
            sources = [
                ContextSourceOut(
                    doc_id=str(source.get("doc_id") or ""),
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
                    sources=sources,
                    created_at=question.created_at,
                )
            )
        question = None
    return turns


def _session_mentions(
    messages: list[MessageRecord],
    cache: ConceptCache,
    *,
    current_doc_id: str,
) -> list[MentionedConceptOut]:
    found: dict[str, MentionedConceptOut] = {}
    for message in messages:
        if message.role != "user":
            continue
        for concept in mentioned_concepts(
            message.content,
            cache.values(),
            exclude_doc_id=current_doc_id,
        ):
            found.setdefault(
                concept.doc_id,
                MentionedConceptOut(doc_id=concept.doc_id, term=concept.term),
            )
    return list(found.values())


def _definition_from_text(text: str) -> str:
    marker = "설명:"
    if marker not in text:
        return text.strip()
    return text.split(marker, 1)[1].strip()


def _display_sources(
    retrieval: RetrievalResult,
    *,
    current_doc_id: str | None,
    minimum_score: float,
) -> list[RetrievedDoc]:
    """화면용 출처만 고른다. LLM 근거 및 저장용 sources에는 영향이 없다."""
    if retrieval.band == "low":
        return []

    candidates = list(retrieval.sources)
    if current_doc_id is not None and not any(
        source.doc_id == current_doc_id for source in candidates
    ):
        current_hit = next(
            (hit for hit in retrieval.concept_hits if hit.doc_id == current_doc_id),
            None,
        )
        if current_hit is not None:
            candidates.insert(0, current_hit)

    selected: list[RetrievedDoc] = []
    seen: set[tuple[str, str]] = set()
    for source in candidates:
        key = (source.collection, source.doc_id)
        if key in seen:
            continue
        if source.doc_id == current_doc_id or source.score >= minimum_score:
            selected.append(source)
            seen.add(key)
    return selected


def resolve_screen(
    catalog: StageCatalog,
    status_service: ConceptStatusReader,
    store: ChatStore,
    user_id: str,
) -> Screen:
    failed = status_service.get_failed_concept(user_id)
    latest = store.get_latest_quiz(user_id, failed.doc_id) if failed is not None else None
    mode, concept = _mode_for(catalog, failed, latest)
    active = store.get_active_session(user_id)
    if mode == "quiz_pending" and active is not None:
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
        concept = find_concept(catalog, active.doc_id, active.stage)
        return MessagePlan(concept, active, None, active.attempt, None)
    if screen.mode == "quiz_pending":
        return MessagePlan(None, None, None, None, None)
    if screen.mode == "relearn":
        if screen.concept is None:
            raise MessageInvariantError("재학습 개념을 찾을 수 없습니다.")
        if request.selected_doc_id is not None and request.selected_doc_id != screen.concept.doc_id:
            raise MessageConflictError("미통과 개념을 먼저 학습해야 합니다.")
        if request.stage is not None and request.stage != screen.concept.stage_id:
            raise MessageConflictError("미통과 개념을 먼저 학습해야 합니다.")
        return MessagePlan(
            screen.concept,
            None,
            "relearn",
            store.get_next_attempt(user_id, screen.concept.doc_id),
            None,
        )
    if request.selected_doc_id is not None:
        stage_id = request.stage or status_service.get_current_stage(user_id)
        try:
            concept = find_concept(catalog, request.selected_doc_id, stage_id)
        except Exception as exc:
            raise MessageConflictError("선택한 개념을 해당 스테이지에서 찾을 수 없습니다.") from exc
        statuses = status_service.get_statuses(user_id, stage_id)
        if statuses.get(concept.doc_id, STATUS_UNLEARNED) != STATUS_UNLEARNED:
            raise MessageConflictError("현재 선택할 수 있는 미학습 개념이 아닙니다.")
        return MessagePlan(
            concept,
            None,
            "keyword",
            store.get_next_attempt(user_id, concept.doc_id),
            stage_id if stage_id == "stage5" else None,
        )
    return MessagePlan(None, None, None, None, None)


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
        if statuses.get(concept.doc_id, STATUS_UNLEARNED) == STATUS_UNLEARNED
    ]
    return detect_concept(
        question=question,
        candidates=candidates,
        cache=cache,
        retrieval=retrieval,
        band_high=settings.band_high,
    )


def _cached_concept(cache: ConceptCache, concept: ConceptRef):
    cached = cache.get(concept.doc_id)
    if cached is None:
        raise MessageInvariantError(f"개념 캐시에 문서가 없습니다: {concept.doc_id}")
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


def _related_for_plan(
    *,
    question: str,
    plan: MessagePlan,
    cached,
    cache: ConceptCache,
    retrieval: RetrievalResult,
    llm: LLMAdapter,
) -> bool:
    if plan.concept is None or cached is None:
        return False
    return is_question_related(
        question=question,
        current=cached,
        cache=cache,
        retrieval=retrieval,
        llm=llm,
        force_true=plan.start_type in {"keyword", "detected"},
    )


def _ensure_answer_suffixes(
    answer: str,
    retrieval: RetrievalResult,
    excluded_term: bool,
) -> str:
    result = answer.strip()
    if retrieval.band == "low" and "경제 학습 범위 밖 질문" not in result:
        result += "\n\n경제 학습 범위 밖 질문입니다."
    if excluded_term and "경제 학습 범위 밖 용어" not in result:
        result += "\n\n경제 학습 범위 밖 용어입니다."
    labels = list(dict.fromkeys(source.label for source in retrieval.sources))
    if labels and "출처:" not in result:
        result += f"\n\n출처: {', '.join(labels)}"
    return result


def _mode_for(
    catalog: StageCatalog,
    failed: FailedConceptView | None,
    latest: LatestQuiz | None,
) -> tuple[ChatMode, ConceptRef | None]:
    if failed is None or latest is None:
        return "normal", None
    concept = find_concept(catalog, failed.doc_id, failed.stage)
    if latest.quiz_status == "failed":
        return "relearn", concept
    if latest.quiz_status in ("pending", "passed"):
        return "quiz_pending", concept
    return "normal", None


def _session_out(record: SessionRecord) -> SessionOut:
    return SessionOut(
        session_id=record.session_id,
        stage=record.stage,
        doc_id=record.doc_id,
        term=record.term,
        attempt=record.attempt,
        start_type=record.start_type,
        status=record.status,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )
