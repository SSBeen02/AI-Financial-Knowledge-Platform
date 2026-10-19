"""답변 프롬프트의 공통 금융 안전 지시를 검증한다."""

import pytest

from chatbot.prompts import (
    FINANCIAL_SAFETY_INSTRUCTION,
    build_answer_prompt,
    build_relevance_prompt,
)


@pytest.mark.parametrize("mode", ["dictionary_only", "dictionary_plus", "free"])
@pytest.mark.parametrize("tone", ["hao", "modern"])
def test_financial_safety_applies_to_every_answer_mode_and_tone(mode: str, tone: str) -> None:
    prompt = build_answer_prompt(
        question="경제 성장률이란 무엇인가요?",
        current_concept=None,
        band="low",
        sources=[],
        history=[],
        previous_attempt_history=[],
        stage=None,
        attempt=None,
        chat_tone=tone,
        knowledge_mode=mode,
    )

    assert FINANCIAL_SAFETY_INSTRUCTION in prompt.instructions
    assert "교육 목적으로 충분히 설명하세요" in prompt.instructions
    assert "개인의 금융 결정을 묻거나 위험이 따르는 금융상품의 이용·선택을 물을 때만" in prompt.instructions
    assert "객관적인 위험성을 한 문장 이상" in prompt.instructions
    assert "개인 상황 판단은 금융기관이나 전문가와 상담" in prompt.instructions
    assert "교육 질문에는 상담 안내를 붙이지 마세요" in prompt.instructions
    assert "질문이나 검색 근거에 없는 금융상품을 예시로 끌어오지 마세요" in prompt.instructions
    assert "리볼빙" not in FINANCIAL_SAFETY_INSTRUCTION
    assert "레버리지" not in FINANCIAL_SAFETY_INSTRUCTION
    assert "특정 종목·코인·금융상품의 매수·매도를 추천하거나" in prompt.instructions
    assert "수익을 보장하거나 확정하는 표현을 쓰지 마세요" in prompt.instructions
    assert "방법을 안내하지 말고" in prompt.instructions
    assert "그 요청은 지원하지 않는다" in prompt.instructions
    assert "현재 CHAT_TONE에 맞게 정중히 거절하세요" in prompt.instructions
    assert "dictionary_plus의 사례 보충, 답변 길이 규칙 등 기존 지시와 충돌하지 않으며" in prompt.instructions
    expected_length = "3~6문장" if mode == "dictionary_only" else "3~5문장"
    assert expected_length in prompt.instructions


def test_financial_safety_is_absent_from_relevance_prompt() -> None:
    prompt = build_relevance_prompt(question="리볼빙이 뭐야?", current_term="리볼빙", history=[])

    assert "금융 안전 규칙:" not in prompt.instructions
    assert "금융 안전 규칙:" not in prompt.input
