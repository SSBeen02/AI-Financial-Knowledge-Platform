"""LLM 프롬프트 템플릿을 한 곳에서 관리한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from chatbot.config import AnswerKnowledgeMode
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
    knowledge_mode: AnswerKnowledgeMode,
    chat_emoji: bool = True,
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
    source_instruction = _source_instruction(
        knowledge_mode, source_labels, chat_tone
    )
    knowledge_instruction = _knowledge_instruction(knowledge_mode)
    length_instruction = _length_instruction(question, knowledge_mode)
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
    emoji_instruction = (
        "핵심 정의나 꼭 기억할 포인트 1~2곳에만 ⭐️, 🕯, 💡 같은 이모지나 이모티콘을 "
        "사용하세요. 답변 전체의 이모지·이모티콘은 합계 3개를 넘기지 마세요. 중요한 문구만 "
        "필요 최소한으로 굵게 표시하고 볼드체를 남발하지 마세요. 이 강조 지시 때문에 사전 "
        "근거의 핵심 정의 문장 내용 자체를 바꾸지 마세요."
        if chat_emoji
        else ""
    )
    instructions = "\n".join(
        part
        for part in (
            "당신은 경제 지식이 부족한 청년에게 경제 개념을 쉽게 설명하는 튜터입니다.",
            answer_tone_instruction(chat_tone),
            length_instruction,
            knowledge_instruction,
            f"현재 학습 개념: {current_term}. 관련 없는 질문에도 답하되 억지로 현재 개념과 연결하지 마세요.",
            repeat_instruction,
            relearn_instruction,
            advanced_instruction,
            emoji_instruction,
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


def _knowledge_instruction(mode: AnswerKnowledgeMode) -> str:
    if mode == "dictionary_plus":
        return (
            "핵심 정의와 사실은 제공된 사전 근거와 어긋나지 않게 유지하세요. 배경, 이런 현상이 "
            "생기는 이유, 생활 사례, 관련 개념과의 연결은 일반적인 경제 지식으로 자유롭게 "
            "보충할 수 있습니다. 다만 근거에 없는 구체적인 숫자·날짜·최신 통계·특정 기업·인물 "
            "사례를 만들지 마세요. 사전 문장을 그대로 옮기지 말고 핵심 의미 → 왜 중요한지 → "
            "학습자의 생활과의 연결 순서로 재구성하세요."
        )
    if mode == "free":
        return (
            "제공된 사전은 참고 자료로만 사용하고 일반 경제 지식을 활용해 자유롭게 설명하세요. "
            "다만 퀴즈는 사전 정의를 기준으로 하므로 핵심 정의와 충돌하면 안 됩니다. 근거에 없는 "
            "구체적인 숫자·날짜·최신 통계·특정 기업·인물 사례를 만들지 마세요."
        )
    return (
        "사실·숫자·정의는 제공된 사전 근거를 따르되, 설명 방식과 문장 구성은 자유롭게 하세요.\n"
        "사전 문장을 그대로 옮기지 말고 핵심 의미 → 왜 중요한지 → 학습자의 생활과의 연결 순서로 재구성하세요.\n"
        "세부 숫자, 유래, 인물 이름은 사용자가 직접 요구했거나 질문 이해에 꼭 필요할 때만 포함하세요.\n"
        "이해를 돕는 일반적인 배경 지식은 사용할 수 있지만, 사전과 다른 사실이나 숫자를 지어내지 마세요."
    )


def _length_instruction(question: str, mode: AnswerKnowledgeMode) -> str:
    if mode == "dictionary_only":
        return "쉬운 말과 생활 속 예시 1개를 사용하고, 본문은 3~6문장 내외로 답하세요."
    detailed = any(
        marker in question.replace(" ", "")
        for marker in ("더자세히", "자세하게", "왜", "예시", "원인", "차이")
    )
    if detailed:
        return (
            "사용자가 이유·예시·상세 설명을 요청했으므로 쉬운 말로 충분히 자세히 답하고, "
            "필요하면 여러 생활 사례와 관련 개념 연결을 포함하세요."
        )
    return "단순 질문이므로 쉬운 말과 생활 속 예시를 사용해 본문을 3~5문장으로 답하세요."


def _source_instruction(
    mode: AnswerKnowledgeMode,
    source_labels: list[str],
    chat_tone: ChatTone,
) -> str:
    if not source_labels:
        return ""
    labels = ", ".join(source_labels)
    if mode == "dictionary_plus":
        supplement = (
            "※ 보충 설명은 일반적인 경제 상식을 바탕으로 했어요"
            if chat_tone == "modern"
            else "※ 보충 설명은 일반적인 경제 상식을 바탕으로 했소"
        )
        return (
            f"마지막에 '핵심 정의 출처: {labels}'를 표시하세요. 사전 밖의 배경·이유·사례·연결을 "
            f"보충했다면 그 다음 줄에 '{supplement}'도 표시하세요."
        )
    if mode == "free":
        return (
            f"사전 내용을 실제로 인용하거나 설명 근거로 사용한 경우에만 마지막에 '출처: {labels}'를 "
            "표시하고, 사용하지 않았다면 출처 문구를 쓰지 마세요."
        )
    return f"검색 근거를 사용했다면 마지막 줄에 '출처: {labels}'라고 쓰세요."


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
