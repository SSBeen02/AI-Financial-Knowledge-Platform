"""챗봇 API 요청·응답 모델."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_serializer, model_validator

ConceptProgress = Literal["미학습", "미통과", "통과"]
QuizStatus = Literal["pending", "passed", "failed"]
Band = Literal["high", "mid", "low"]
ChatMode = Literal["normal", "relearn", "quiz_pending"]
SessionStartType = Literal["keyword", "detected", "relearn"]
SessionStatus = Literal["active", "completed"]


class _OmitAbsentImages(BaseModel):
    """payload에 images가 없을 때는 응답 필드 자체를 생략한다."""

    images: list[str] | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> Any:
        data = handler(self)
        if isinstance(data, dict) and self.images is None:
            data.pop("images", None)
        return data


class ConceptOut(BaseModel):
    doc_id: str
    term: str
    term_full: str
    subcategory: str
    order: int


class StageOut(BaseModel):
    id: str
    name_ko: str


class ConceptsResponse(BaseModel):
    mode: ChatMode
    stage: StageOut
    concepts: list[ConceptOut]
    next_offset: int | None
    has_more: bool
    locked_concept: ConceptOut | None = None
    notice: str | None = None
    suggested_message: str | None = None


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    selected_doc_id: str | None = None
    stage: Literal["stage5"] | None = None

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("메시지를 입력해 주세요.")
        return text

    @field_validator("selected_doc_id")
    @classmethod
    def _blank_doc_id_is_absent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @model_validator(mode="after")
    def _stage_requires_selected_concept(self) -> MessageIn:
        if self.stage is not None and self.selected_doc_id is None:
            raise ValueError("stage는 selected_doc_id와 함께 보내야 합니다.")
        return self


class SourceOut(_OmitAbsentImages):
    doc_id: str
    term: str
    score: float
    collection: str
    label: str


class ConceptStateOut(BaseModel):
    doc_id: str
    term: str
    stage: str
    status: ConceptProgress
    attempt: int


class MessageResponse(BaseModel):
    answer: str
    session_id: str | None
    session_started: bool
    concept: ConceptStateOut | None
    is_related: bool
    band: Band
    top_score: float
    sources: list[SourceOut]
    display_sources: list[SourceOut]
    message_id: str


class SessionOut(BaseModel):
    session_id: str
    stage: str
    doc_id: str
    term: str
    attempt: int
    start_type: SessionStartType
    status: SessionStatus
    created_at: datetime
    completed_at: datetime | None = None


class StateResponse(BaseModel):
    mode: ChatMode
    active_session: SessionOut | None
    locked_concept: ConceptOut | None = None
    notice: str | None = None


class QuizResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool


class MentionedConceptOut(BaseModel):
    doc_id: str
    term: str


class ContextSourceOut(_OmitAbsentImages):
    """학습 맥락 근거. 컬렉션명과 출처 라벨을 함께 남긴다."""

    doc_id: str
    collection: str
    label: str


class LearningTurnOut(BaseModel):
    question: str
    answer: str
    sources: list[ContextSourceOut]
    created_at: datetime


class LearningConceptOut(BaseModel):
    doc_id: str
    term: str
    stage: str
    status: ConceptProgress
    attempt: int
    definition: str


class LearningContextOut(BaseModel):
    session_id: str
    user_id: str
    status: Literal["completed"]
    quiz_status: QuizStatus
    concept: LearningConceptOut
    turns: list[LearningTurnOut]
    mentioned_concepts: list[MentionedConceptOut]
    completed_at: datetime


class LearningContextListItem(BaseModel):
    session_id: str
    doc_id: str
    term: str
    status: Literal["completed"]
    quiz_status: QuizStatus
    completed_at: datetime


class MessageListItem(BaseModel):
    message_id: str
    session_id: str | None
    role: Literal["user", "assistant"]
    content: str
    is_related: bool | None = None
    band: Band | None = None
    top_score: float | None = None
    sources: list[SourceOut] | None = None
    latency_ms: int | None = None
    created_at: datetime
