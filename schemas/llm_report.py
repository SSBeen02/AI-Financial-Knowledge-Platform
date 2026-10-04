from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainLevelComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    domain_label: str
    score: float
    diagnosis: str = Field(description="이 영역에서 무엇을 이해하고 있고 무엇을 더 보면 좋은지, 학습자에게 차근차근 설명하는 두 문장")


class LevelDiagnosis(BaseModel):
    """영역별 점수를 바탕으로 한 전체 실력 진단."""

    model_config = ConfigDict(extra="forbid")

    overall_level: Literal["우수", "양호", "보통", "보완필요"]
    summary: str = Field(description="전체 결과가 무엇을 뜻하는지 학습자에게 따뜻하게 풀어 설명하는 두세 문장")
    domain_comments: list[DomainLevelComment]


class WrongAnswerItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    concept: str
    domain: str
    domain_label: str
    vulnerability: str = Field(description="이 개념의 어떤 점을 헷갈렸는지 쉽게 풀어 주는 문장")


class WrongAnswerAnalysis(BaseModel):
    """틀린 문항에서 보이는 핵심 취약점."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    items: list[WrongAnswerItem]


class RecommendationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    priority: int = Field(description="1이 가장 먼저 학습할 항목")
    domain: str
    domain_label: str
    focus: str = Field(description="이번 학습에서 보면 좋은 주제")
    guide: str = Field(description="1단계부터 차근차근 안내하는 실천 순서")


class LlmReportAnalysis(BaseModel):
    """OpenAI structured output으로 받는 맞춤 리포트."""

    model_config = ConfigDict(extra="forbid")

    level_diagnosis: LevelDiagnosis
    wrong_answer_analysis: WrongAnswerAnalysis
    recommendations: list[RecommendationItem]
