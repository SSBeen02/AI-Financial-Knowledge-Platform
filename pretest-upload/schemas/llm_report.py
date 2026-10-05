from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DomainLevelComment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    domain_label: str
    score: float
    diagnosis: str = Field(description="이번 영역 문항에서 확인된 범위와 대표 구분 기준. 1~2문장, 100자 안팎")


class LevelDiagnosis(BaseModel):
    """영역별 점수를 바탕으로 한 전체 실력 진단."""

    model_config = ConfigDict(extra="forbid")

    overall_level: Literal["우수", "양호", "보통", "보완필요"]
    summary: str = Field(description="이번 테스트에서 확인한 결과와 다음 행동. 일반 실력으로 확대하지 않는 짧은 2문장, 140자 안팎")
    domain_comments: list[DomainLevelComment]


class WrongAnswerItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    concept: str
    domain: str
    domain_label: str
    vulnerability: str = Field(description="실제 선택한 보기와 정답의 핵심 차이, 질문에서 정답을 가르는 단서. 짧은 2문장, 100~160자 안팎")


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
    focus: str = Field(description="학습 주제 제목. 약점 보완·체크리스트라는 말을 넣지 않는 25자 안팎")
    guide: str = Field(description="주제별 3~5문장의 풍부한 단일 문단. 실제 혼동 지점, 본질적인 구분 기준, 실전 접근 전략을 자연스럽게 연결. 줄바꿈·대괄호 태그·불렛·번호·마크다운 강조·숙제형 과제 금지, 문장 어미 다양화")


class LlmReportAnalysis(BaseModel):
    """OpenAI structured output으로 받는 맞춤 리포트."""

    model_config = ConfigDict(extra="forbid")

    level_diagnosis: LevelDiagnosis
    wrong_answer_analysis: WrongAnswerAnalysis
    recommendations: list[RecommendationItem]
