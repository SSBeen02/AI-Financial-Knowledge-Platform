"""LLM 프롬프트 템플릿을 한 곳에서 관리한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from chatbot.retrieval import CachedConcept, RetrievedDoc
from chatbot.schemas import Band
from chatbot.tone import (
    ChatTone,
    answer_tone_instruction,
)


@dataclass(frozen=True)
class HistoryTurn:
    question: str
    answer: str


@dataclass(frozen=True)
class Prompt:
    instructions: str
    input: str


def build_answer_prompt(
    *,
    question: str,
    current_concept: CachedConcept | None,
    band: Band,
    sources: Sequence[RetrievedDoc],
    history: Sequence[HistoryTurn],
    previous_attempt_history: Sequence[HistoryTurn],
    stage: str | None,
    attempt: int | None,
    chat_tone: ChatTone,
) -> Prompt:
    current_term = current_concept.term if current_concept is not None else "없음"
    band_instruction = {
        "high": "제공된 검색 근거를 우선 사용해 답하세요.",
        "mid": "검색 근거가 질문과 직접 관련 있을 때만 사용하고, 무리하게 연결하지 마세요.",
        "low": (
            "검색 근거를 사용하지 말고 일반 지식으로만 답하세요."
        ),
    }[band]
    source_labels = list(dict.fromkeys(source.label for source in sources))
    source_instruction = (
        f"검색 근거를 사용했다면 마지막 줄에 '출처: {', '.join(source_labels)}'라고 쓰세요."
        if source_labels
        else ""
    )
    repeat_instruction = (
        "같은 세션에서 이미 설명한 정의와 사실은 한 문장 이하로 짧게 언급하고, "
        "원인·영향·비슷한 개념과의 차이·적용 상황 중 아직 다루지 않은 새 각도로 설명하세요. "
        "이전 답변의 숫자·유래·생활 예시를 반복하지 마세요."
        if history
        else ""
    )
    relearn_instruction = (
        f"현재 재학습 {attempt}회차입니다. 아래 이전 학습 시도의 답변과 다른 설명 순서, "
        "비유, 생활 예시를 사용하세요."
        if attempt is not None and attempt >= 2
        else ""
    )
    advanced_instruction = (
        "Stage 5 심화 학습입니다. 사용자가 기초 정의는 안다고 보고, TESAT·매경TEST에서 "
        "자주 묻는 구분 포인트와 함정, 관련 개념과의 연결을 중심으로 설명하세요."
        if stage == "stage5"
        else ""
    )
    instructions = "\n".join(
        part
        for part in (
            "당신은 경제 지식이 부족한 청년에게 경제 개념을 쉽게 설명하는 튜터입니다.",
            answer_tone_instruction(chat_tone),
            "쉬운 말과 생활 속 예시 1개를 사용하고, 본문은 3~6문장 내외로 답하세요.",
            "사실·숫자·정의는 제공된 사전 근거를 따르되, 설명 방식과 문장 구성은 자유롭게 하세요.",
            "사전 문장을 그대로 옮기지 말고 핵심 의미 → 왜 중요한지 → 학습자의 생활과의 연결 순서로 재구성하세요.",
            "세부 숫자, 유래, 인물 이름은 사용자가 직접 요구했거나 질문 이해에 꼭 필요할 때만 포함하세요.",
            "이해를 돕는 일반적인 배경 지식은 사용할 수 있지만, 사전과 다른 사실이나 숫자를 지어내지 마세요.",
            f"현재 학습 개념: {current_term}. 관련 없는 질문에도 답하되 억지로 현재 개념과 연결하지 마세요.",
            repeat_instruction,
            relearn_instruction,
            advanced_instruction,
            band_instruction,
            source_instruction,
        )
        if part
    )

    context_parts: list[str] = []
    if current_concept is not None:
        context_parts.append(
            f"[현재 개념] {current_concept.concept_id} {current_concept.term}: {current_concept.text}"
        )
    for source in sources:
        context_parts.append(f"[{source.concept_id}] {source.term}: {source.text}")
    context = "\n\n".join(context_parts) or "제공된 근거 없음"

    history_text = "\n".join(
        f"사용자: {turn.question}\n튜터: {turn.answer}" for turn in history
    ) or "이전 대화 없음"
    previous_attempt_text = "\n".join(
        f"사용자: {turn.question}\n튜터: {turn.answer}" for turn in previous_attempt_history
    ) or "이전 시도 대화 없음"
    user_input = (
        f"[근거]\n{context}\n\n"
        f"[이전 학습 시도의 최근 대화]\n{previous_attempt_text}\n\n"
        f"[같은 세션의 최근 대화]\n{history_text}\n\n"
        f"[현재 질문]\n{question}"
    )
    return Prompt(instructions=instructions, input=user_input)


def build_relevance_prompt(
    *,
    question: str,
    current_term: str,
    history: Sequence[HistoryTurn],
) -> Prompt:
    history_text = "\n".join(
        f"사용자: {turn.question}\n튜터: {turn.answer}" for turn in history[-2:]
    ) or "이전 대화 없음"
    return Prompt(
        instructions=(
            "경제 학습 질문의 관련성을 판정하세요. 다른 경제 용어만 직접 언급됐더라도 현재 개념과의 "
            "비교·대조·인과·연결 질문이면 yes입니다. 다른 용어만 독립적으로 설명해 달라는 질문이면 "
            "no입니다. 설명하지 말고 yes 또는 no 한 단어만 답하세요."
        ),
        input=(
            f"현재 학습 개념: {current_term}\n"
            f"최근 대화:\n{history_text}\n"
            f"현재 질문: {question}\n"
            "이 질문은 현재 개념 학습과 관련 있나요?"
        ),
    )
