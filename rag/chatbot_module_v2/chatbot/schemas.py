"""챗봇 API 요청·응답 모델."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_serializer

ConceptProgress = Literal["not_started", "in_progress", "passed"]
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
    concept_id: str
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
    concept_id: str | None = None

    @field_validator("message")
    @classmethod
    def _message_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("메시지를 입력해 주세요.")
        return text

    @field_validator("concept_id")
    @classmethod
    def _blank_concept_id_is_absent(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

class SourceOut(_OmitAbsentImages):
    concept_id: str
    term: str
    score: float
    collection: str
    label: str


class ConceptStateOut(BaseModel):
    concept_id: str
    term: str
    stage: str
    status: ConceptProgress
    attempt: int


class SuggestedConceptOut(BaseModel):
    concept_id: str
    term: str


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
    notice: str | None = None
    suggested_concept: SuggestedConceptOut | None = None


class SessionOut(BaseModel):
    session_id: str
    stage: str
    concept_id: str
    term: str
    attempt: int
    start_type: SessionStartType
    status: SessionStatus
    created_at: datetime
    completed_at: datetime | None = None


class CurrentStageProgressOut(BaseModel):
    stage_id: str
    name_ko: str
    total_count: int
    passed_count: int
    in_progress_count: int
    not_started_count: int
    remaining_count: int
    percent: int


class StageProgressOut(CurrentStageProgressOut):
    unlocked: bool
    completed: bool


class ProgressResponse(BaseModel):
    current: CurrentStageProgressOut
    stages: list[StageProgressOut]


class ConceptStatusLabelsOut(BaseModel):
    """화면 표시용 문구. 저장·연동 값은 ConceptProgress 영문 코드를 사용한다."""

    not_started: str
    in_progress: str
    passed: str


class StateResponse(BaseModel):
    mode: ChatMode
    active_session: SessionOut | None
    locked_concept: ConceptOut | None = None
    notice: str | None = None
    complete_hint: str | None = None
    learning_guide: str
    status_labels: ConceptStatusLabelsOut
    progress: CurrentStageProgressOut


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str


class QuizResultIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool


class MentionedConceptOut(BaseModel):
    concept_id: str
    term: str


class ContextSourceOut(_OmitAbsentImages):
    """학습 맥락 근거. 컬렉션명과 출처 라벨을 함께 남긴다."""

    concept_id: str
    collection: str
    label: str


class LearningTurnOut(BaseModel):
    question: str
    answer: str
    is_related: bool = True
    sources: list[ContextSourceOut]
    created_at: datetime


class LearningConceptOut(BaseModel):
    concept_id: str
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
    concept_id: str
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
    display_sources: list[SourceOut]
    created_at: datetime
