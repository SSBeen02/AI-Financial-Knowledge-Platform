"""LLM 프롬프트 템플릿을 한 곳에서 관리한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from chatbot.retrieval import CachedConcept, RetrievedDoc
from chatbot.schemas import Band


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
    excluded_term: bool,
) -> Prompt:
    current_term = current_concept.term if current_concept is not None else "없음"
    band_instruction = {
        "high": "제공된 검색 근거를 우선 사용해 답하세요.",
        "mid": "검색 근거가 질문과 직접 관련 있을 때만 사용하고, 무리하게 연결하지 마세요.",
        "low": (
            "검색 근거를 사용하지 말고 일반 지식으로만 답하세요. "
            "답변 끝에 '경제 학습 범위 밖 질문입니다.'라고 안내하세요."
        ),
    }[band]
    excluded_instruction = (
        "검색 1위가 제외 용어이므로 답변 끝에 '경제 학습 범위 밖 용어입니다.'라고 안내하세요."
        if excluded_term
        else ""
    )
    source_labels = list(dict.fromkeys(source.label for source in sources))
    source_instruction = (
        f"검색 근거를 사용했다면 마지막 줄에 '출처: {', '.join(source_labels)}'라고 쓰세요."
        if source_labels
        else ""
    )
    instructions = "\n".join(
        part
        for part in (
            "당신은 경제 지식이 부족한 청년에게 경제 개념을 쉽게 설명하는 튜터입니다.",
            "쉬운 말과 생활 속 예시 1개를 사용하고, 본문은 3~6문장 내외로 답하세요.",
            "제공된 근거에 없는 사실을 단정하지 마세요.",
            f"현재 학습 개념: {current_term}. 관련 없는 질문에도 답하되 억지로 현재 개념과 연결하지 마세요.",
            band_instruction,
            excluded_instruction,
            source_instruction,
        )
        if part
    )

    context_parts: list[str] = []
    if current_concept is not None:
        context_parts.append(
            f"[현재 개념] {current_concept.doc_id} {current_concept.term}: {current_concept.text}"
        )
    for source in sources:
        context_parts.append(f"[{source.doc_id}] {source.term}: {source.text}")
    context = "\n\n".join(context_parts) or "제공된 근거 없음"

    history_text = "\n".join(
        f"사용자: {turn.question}\n튜터: {turn.answer}" for turn in history
    ) or "이전 대화 없음"
    user_input = (
        f"[근거]\n{context}\n\n"
        f"[같은 세션의 최근 대화]\n{history_text}\n\n"
        f"[현재 질문]\n{question}"
    )
    return Prompt(instructions=instructions, input=user_input)


def build_relevance_prompt(*, question: str, current_term: str) -> Prompt:
    return Prompt(
        instructions=(
            "경제 학습 질문의 관련성을 판정하세요. 설명하지 말고 yes 또는 no 한 단어만 답하세요."
        ),
        input=f"현재 학습 개념: {current_term}\n질문: {question}\n이 질문은 현재 개념 학습과 관련 있나요?",
    )
