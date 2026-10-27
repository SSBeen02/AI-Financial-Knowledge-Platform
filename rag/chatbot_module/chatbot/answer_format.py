"""사용자에게 보이는 LLM 답변을 일반 텍스트로 정리한다."""

from __future__ import annotations

import re

from chatbot.schemas import SafetyLevel

ADVICE_DISCLAIMER = "AI 작성, 투자 조언 아님"

_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0E\uFE0F\u200D\u20E3]")
_EMOTICON = re.compile(r"(?<!\w)(?:[:;=8][\-oO]?[)(DPp/\\|]|\^\^|ㅠㅠ|ㅜㅜ)(?!\w)")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_SOURCE_LINE = re.compile(r"^\s*(?:핵심 정의\s*)?출처\s*:\s*.*$", re.MULTILINE)
_MODEL_FOOTER_LINE = re.compile(
    r"^\s*(?:참고한 사전 항목\s*:|※\s*(?:핵심 정의는|보충 설명은)).*$",
    re.MULTILINE,
)


class IncrementalAnswerFormatter:
    """완성된 문장과 줄만 정리해 내보내는 공통 답변 포매터."""

    def __init__(self) -> None:
        self.pending = ""
        self.body = ""
        self.model_cited = False
        self.has_input = False
        self._whitespace = ""

    def feed(self, chunk: str) -> list[str]:
        self.has_input |= bool(chunk)
        self.pending += chunk
        deltas: list[str] = []
        while True:
            boundary = self._boundary()
            if boundary is None:
                break
            piece, self.pending = self.pending[:boundary], self.pending[boundary:]
            delta = self._format_piece(piece)
            if delta:
                deltas.append(delta)
        return deltas

    def finish(self) -> list[str]:
        piece, self.pending = self.pending, ""
        delta = self._format_piece(piece)
        return [delta] if delta else []

    def _boundary(self) -> int | None:
        # 출처와 고지 줄은 끝까지 보관해 모델의 문구가 화면에 새지 않도록 한다.
        first_line = self.pending.split("\n", 1)[0]
        source_line = bool(re.match(
            r"\s*(?:(?:핵심 정의\s*)?출처\s*:|참고한 사전 항목\s*:|※\s*(?:핵심 정의는|보충 설명은))",
            first_line,
        ))
        advice_line = first_line.lstrip().startswith(ADVICE_DISCLAIMER)
        for index, char in enumerate(self.pending[:160]):
            if char == "\n":
                return index + 1
            if char in ".?!。" and not source_line and not advice_line:
                # 마크다운 링크의 URL이나 숫자 중간에서 문장을 자르지 않는다.
                link_start = self.pending.rfind("](", 0, index)
                if link_start >= 0 and ")" not in self.pending[link_start:index]:
                    continue
                if (char == "." and index > 0 and index + 1 < len(self.pending)
                        and self.pending[index - 1].isdigit()
                        and self.pending[index + 1].isdigit()):
                    continue
                return index + 1
        # 긴 문장도 무한히 버퍼에 쌓이지 않게 단어 경계에서 내보낸다.
        if len(self.pending) >= 160 and not source_line and not advice_line:
            split = self.pending.rfind(" ", 0, 120)
            if split > 0:
                # 열린 링크는 정리 전까지 원문 그대로 보관한다.
                link_start = self.pending.rfind("](", 0, split)
                if link_start >= 0 and ")" not in self.pending[link_start:split]:
                    return None
                return split + 1
        return None

    def _format_piece(self, piece: str) -> str:
        if not piece:
            return ""
        leading = re.match(r"\s*", piece).group()
        content = piece[len(leading):]
        trailing = re.search(r"\s*$", content).group()
        content = content[:len(content) - len(trailing)] if trailing else content
        clean, cited = normalize_answer_text(content)
        self.model_cited |= cited
        clean = clean.replace(ADVICE_DISCLAIMER, "").strip()
        if not clean:
            self._whitespace += piece if not content else leading + trailing
            return ""
        whitespace = self._whitespace + leading
        self._whitespace = trailing
        if not self.body:
            separator = ""
        elif "\n" in whitespace:
            separator = "\n\n" if whitespace.count("\n") >= 2 else "\n"
        elif whitespace:
            separator = " "
        else:
            separator = ""
        delta = separator + clean
        self.body += delta
        return delta


def normalize_answer_text(answer: str) -> tuple[str, bool]:
    """(정리된 본문, 모델이 출처를 표기했는지)를 반환한다."""
    text = answer.replace("**", "").replace("__", "").replace("`", "")
    text = _LINK.sub(r"\1 (\2)", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    cited = bool(_SOURCE_LINE.search(text))
    text = _SOURCE_LINE.sub("", text)
    text = _MODEL_FOOTER_LINE.sub("", text)
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
