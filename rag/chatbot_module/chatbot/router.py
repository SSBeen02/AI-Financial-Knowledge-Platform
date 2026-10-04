"""챗봇 API 라우터. 엔드포인트만 둔다."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from chatbot.concepts import ConceptCatalogError, StageCatalog, StageQueryError
from chatbot.config import Settings
from chatbot.deps import (
    get_cached_settings,
    get_chat_store,
    get_concept_cache,
    get_concept_status_service,
    get_llm_adapter,
    get_retriever,
    get_stage_catalog,
)
from chatbot.integrations import ConceptStatusError, ConceptStatusService, CurrentUserId
from chatbot.llm import LLMAdapter
from chatbot.retrieval import ConceptCache, Retriever
from chatbot.schemas import (
    ConceptsResponse,
    LearningContextListItem,
    LearningContextOut,
    MessageIn,
    MessageResponse,
    QuizResultIn,
    SessionOut,
    StateResponse,
)
from chatbot.service import (
    ExternalServiceError,
    LearningCompletionError,
    MessageConflictError,
    MessageInvariantError,
    QuizResultConflictError,
    ScreenInvariantError,
    SessionNotFound,
    complete_learning_session,
    get_chat_state,
    get_learning_context,
    get_user_session,
    list_concept_page,
    list_learning_contexts,
    prepare_message,
    report_quiz_result,
    send_message,
    stream_message_events,
)
from chatbot.store import ChatStore, ChatStoreError

router = APIRouter(prefix="/chat", tags=["chat"])


def _call[T](action: Callable[[], T]) -> T:
    try:
        return action()
    except StageQueryError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.") from exc
    except ConceptCatalogError as exc:
        raise HTTPException(status_code=500, detail=exc.detail) from exc
    except ConceptStatusError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ChatStoreError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except ScreenInvariantError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except MessageConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except ExternalServiceError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    except MessageInvariantError as exc:
        raise HTTPException(status_code=500, detail=exc.detail) from exc
    except LearningCompletionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    except QuizResultConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc


@router.get("/concepts", response_model=ConceptsResponse)
def list_concepts(
    user_id: CurrentUserId,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1)] = 5,
    stage: Annotated[str | None, Query()] = None,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
    catalog: StageCatalog = Depends(get_stage_catalog),
    store: ChatStore = Depends(get_chat_store),
) -> ConceptsResponse:
    return _call(
        lambda: list_concept_page(
            catalog,
            status_service,
            store,
            user_id,
            offset=offset,
            limit=limit,
            stage=stage,
        )
    )


@router.get("/state", response_model=StateResponse)
def read_state(
    user_id: CurrentUserId,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
    catalog: StageCatalog = Depends(get_stage_catalog),
    store: ChatStore = Depends(get_chat_store),
) -> StateResponse:
    return _call(lambda: get_chat_state(catalog, status_service, store, user_id))


@router.get("/sessions/{session_id}", response_model=SessionOut)
def read_session(
    session_id: str,
    user_id: CurrentUserId,
    store: ChatStore = Depends(get_chat_store),
) -> SessionOut:
    return _call(lambda: get_user_session(store, user_id, session_id))


@router.post("/messages", response_model=MessageResponse)
def create_message(
    request: MessageIn,
    user_id: CurrentUserId,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
    catalog: StageCatalog = Depends(get_stage_catalog),
    store: ChatStore = Depends(get_chat_store),
    cache: ConceptCache = Depends(get_concept_cache),
    retriever: Retriever = Depends(get_retriever),
    llm: LLMAdapter = Depends(get_llm_adapter),
    settings: Settings = Depends(get_cached_settings),
) -> MessageResponse:
    return _call(
        lambda: send_message(
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
    )


@router.post("/messages/stream", response_class=StreamingResponse)
def create_message_stream(
    request: MessageIn,
    http_request: Request,
    user_id: CurrentUserId,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
    catalog: StageCatalog = Depends(get_stage_catalog),
    store: ChatStore = Depends(get_chat_store),
    cache: ConceptCache = Depends(get_concept_cache),
    retriever: Retriever = Depends(get_retriever),
    llm: LLMAdapter = Depends(get_llm_adapter),
    settings: Settings = Depends(get_cached_settings),
) -> StreamingResponse:
    prepared = _call(
        lambda: prepare_message(
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
    )
    events = stream_message_events(
        prepared=prepared,
        status_service=status_service,
        store=store,
        llm=llm,
        is_disconnected=http_request.is_disconnected,
    )
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/complete", response_model=LearningContextOut)
def complete_session(
    session_id: str,
    user_id: CurrentUserId,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
    store: ChatStore = Depends(get_chat_store),
    cache: ConceptCache = Depends(get_concept_cache),
) -> LearningContextOut:
    return _call(
        lambda: complete_learning_session(
            status_service=status_service,
            store=store,
            cache=cache,
            user_id=user_id,
            session_id=session_id,
        )
    )


@router.get("/sessions/{session_id}/learning-context", response_model=LearningContextOut)
def read_learning_context(
    session_id: str,
    user_id: CurrentUserId,
    store: ChatStore = Depends(get_chat_store),
) -> LearningContextOut:
    return _call(lambda: get_learning_context(store, user_id, session_id))


@router.get("/learning-contexts", response_model=list[LearningContextListItem])
def read_learning_contexts(
    user_id: CurrentUserId,
    status: Annotated[str, Query()] = "completed",
    store: ChatStore = Depends(get_chat_store),
) -> list[LearningContextListItem]:
    if status != "completed":
        raise HTTPException(status_code=400, detail="status는 completed만 지원합니다.")
    return _call(lambda: list_learning_contexts(store, user_id))


@router.post("/sessions/{session_id}/quiz-result", response_model=LearningContextOut)
def create_quiz_result(
    session_id: str,
    request: QuizResultIn,
    user_id: CurrentUserId,
    status_service: ConceptStatusService = Depends(get_concept_status_service),
    store: ChatStore = Depends(get_chat_store),
) -> LearningContextOut:
    return _call(
        lambda: report_quiz_result(
            status_service=status_service,
            store=store,
            user_id=user_id,
            session_id=session_id,
            passed=request.passed,
        )
    )
