from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class QuizChoicePublic(BaseModel):
    key: str
    text: str


class QuizQuestionPublic(BaseModel):
    """조회 응답. 정답과 해설은 포함하지 않습니다."""

    question_index: int
    question_type: Literal["ox", "situation"]
    prompt: str
    choices: list[QuizChoicePublic]


class QuizSetPublicResponse(BaseModel):
    id: str
    status: Literal["pending", "processing", "completed", "failed"]
    concept_id: str
    learning_session_id: str
    stage_id: str | None = None
    questions: list[QuizQuestionPublic]
    created_at: str


class SubmittedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_index: int = Field(ge=1, le=3)
    answer: str = Field(min_length=1, max_length=500)


class SubmitQuizRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    submitted_answers: list[SubmittedAnswer] = Field(min_length=3, max_length=3)
    idempotency_key: str = Field(min_length=1, max_length=200)


class QuizQuestionResult(BaseModel):
    question_index: int
    question_type: Literal["ox", "situation"]
    prompt: str
    submitted_answer: str
    is_correct: bool
    answer: str
    explanation: str


class LearningModuleResult(BaseModel):
    """안유빈 학습 관리 모듈에 넘기는 내부 결과."""

    submission_id: str
    concept_id: str
    correct_count: int
    is_passed: bool


class SubmitQuizResponse(BaseModel):
    submission_id: str
    quiz_set_id: str
    is_correct_list: list[bool]
    correct_count: int
    is_passed: bool
    results: list[QuizQuestionResult]
    learning_module_result: LearningModuleResult
    created_at: str


class LearningNoteItem(BaseModel):
    quiz_set_id: str
    submission_id: str | None
    concept_id: str
    stage_id: str | None
    learning_session_id: str
    question_index: int
    question_type: Literal["ox", "situation"]
    prompt: str
    choices: list[QuizChoicePublic]
    submitted_answer: str | None
    is_correct: bool | None
    answer: str | None
    explanation: str | None
    is_passed: bool | None
    created_at: str


class LearningNotesResponse(BaseModel):
    items: list[LearningNoteItem]
    page: int
    page_size: int
    total: int


class CreatedQuizSet(BaseModel):
    """학습 모듈이 받는 퀴즈 세트. 세션 하나에는 이 세트가 하나이고, 안에 문항 3개가 있습니다."""

    id: str
    status: Literal["pending", "processing", "completed", "failed"]
    concept_id: str
    learning_session_id: str
    stage_id: str | None = None
    created_at: str

    @property
    def quiz_set_id(self) -> str:
        return self.id


class GeneratedChoice(BaseModel):
    key: str
    text: str


class GeneratedQuestion(BaseModel):
    question_index: int
    question_type: Literal["ox", "situation"]
    prompt: str
    choices: list[GeneratedChoice]
    answer: str
    explanation: str


class GeneratedQuizPayload(BaseModel):
    questions: list[GeneratedQuestion]


LearningContext = str | dict[str, Any]
NoteFilter = Literal["all", "correct", "wrong"]
