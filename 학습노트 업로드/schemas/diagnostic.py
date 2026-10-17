from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from schemas.llm_report import LlmReportAnalysis


class QuestionPublic(BaseModel):
    id: str
    domain: str
    domain_label: str
    category: str
    difficulty: int
    question: str
    options: list[str]


ReportStatus = Literal["pending", "processing", "completed", "failed"]


class StartDiagnosticResponse(BaseModel):
    id: str
    user_id: str
    status: Literal["pending"]
    started_at: str
    total_questions: int
    questions: list[QuestionPublic]


class AnswerSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    selected_answer: int = Field(
        strict=True,
        ge=1,
        description="보기 번호. 1이 첫 번째 보기이며, 보기 문자열의 '1)' 접두와 같은 값입니다.",
    )


class SubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[AnswerSubmission] = Field(min_length=1, max_length=1000)


class Explanation(BaseModel):
    correct: str
    options_detail: list[str]


class QuestionResult(BaseModel):
    question_id: str
    domain: str
    domain_label: str
    category: str
    difficulty: int
    concept: str
    question: str
    options: list[str]
    selected_answer: int
    correct_answer: int
    is_correct: bool
    explanation: Explanation


class DomainScore(BaseModel):
    domain: str
    domain_label: str
    total_questions: int
    correct_count: int
    incorrect_count: int
    score: float
    is_vulnerable: bool


class ScoreSummary(BaseModel):
    total_questions: int
    correct_count: int
    incorrect_count: int
    score: float
    level: Literal["우수", "양호", "보통", "보완필요"]
    vulnerable_threshold: float
    weakest_domain: str | None
    weakest_domain_label: str | None
    analysis: str


class SubmitResponse(BaseModel):
    id: str
    report_id: str
    user_id: str
    status: Literal["processing", "completed", "failed"]
    submitted_at: str
    summary: ScoreSummary
    domain_scores: list[DomainScore]
    question_results: list[QuestionResult]


class Vulnerability(BaseModel):
    domain: str
    domain_label: str
    score: float
    correct_count: int
    total_questions: int
    severity: Literal["high", "medium"]
    missed_concepts: list[str]
    missed_question_ids: list[str]
    recommendation: str


class ReportError(BaseModel):
    code: str
    message: str


class ReportResponse(BaseModel):
    id: str
    diagnostic_id: str
    user_id: str
    status: ReportStatus
    created_at: str
    summary: ScoreSummary | None = None
    domain_scores: list[DomainScore] | None = None
    llm_report: LlmReportAnalysis | None = None
    error: ReportError | None = None
    vulnerabilities: list[Vulnerability] | None = None
    question_results: list[QuestionResult] | None = None
