"""사용자에게 보이는 LLM 답변을 일반 텍스트로 정리한다."""

from __future__ import annotations

import re

from chatbot.schemas import SafetyLevel

ADVICE_DISCLAIMER = "AI 작성, 투자 조언 아님"

_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0E\uFE0F\u200D\u20E3]")
_EMOTICON = re.compile(r"(?<!\w)(?:[:;=8][\-oO]?[)(DPp/\\|]|\^\^|ㅠㅠ|ㅜㅜ)(?!\w)")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_SOURCE_LINE = re.compile(r"^\s*(?:핵심 정의\s*)?출처\s*:\s*.*$", re.MULTILINE)


def normalize_answer_text(answer: str) -> tuple[str, bool]:
    """(정리된 본문, 모델이 출처를 표기했는지)를 반환한다."""
    text = answer.replace("**", "").replace("__", "").replace("`", "")
    text = _LINK.sub(r"\1 (\2)", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    cited = bool(_SOURCE_LINE.search(text))
    text = _SOURCE_LINE.sub("", text)
    text = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", text)
    text = _EMOJI.sub("", text)
    text = _EMOTICON.sub("", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip(), cited


def with_advice_disclaimer(answer: str, question: str, safety_level: SafetyLevel) -> str:
    """질문의 의도와 실제 답변을 확인해 고정 고지를 최대 한 번 표시한다."""
    body = answer.replace(ADVICE_DISCLAIMER, "")
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if safety_level == "BLOCK":
        return body

    compact = re.sub(r"\s+", "", question.casefold())
    finance_topic = any(term in compact for term in (
        "투자", "주식", "종목", "펀드", "etf", "채권", "코인", "가상자산",
        "대출", "금융상품", "매수", "매도",
    ))
    personal_decision = finance_topic and any(term in compact for term in (
        "지금사도", "사도될까", "팔아도", "매수할까", "매도할까", "골라줘",
        "추천해", "선택해", "대출받을까", "어느상품", "내게맞", "나한테맞",
        "내소득에맞", "제소득에맞", "내상황에맞", "제상황에맞",
        "한도늘", "한도최대", "전부넣",
    ))
    comparison = any(term in compact for term in ("비교", "위험분석", "위험성분석", "투자위험"))
    specific_product = (
        ("특정" in compact and finance_topic)
        or any(term in compact for term in ("이상품", "해당상품", "이etf", "해당etf"))
        or bool(re.search(r"\b(?:[A-Z]{2,}\s*\d{2,4}|\d{6})\b", question))
    )
    answer_analyzes_decision = any(term in body for term in (
        "판단", "위험", "손실", "비용", "수수료", "금리", "상환", "변동성", "비교 기준",
    ))
    if answer_analyzes_decision and (personal_decision or (comparison and specific_product)):
        return f"{body}\n\n{ADVICE_DISCLAIMER}"
    return body
