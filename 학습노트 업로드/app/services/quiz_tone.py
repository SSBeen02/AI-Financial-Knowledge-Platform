"""퀴즈 해설의 문장 종결만 하오체로 통일한다. 수치·정답·본문은 유지한다."""
import re


def explanation_in_hao(text: str) -> str:
    # 문장 끝 또는 괄호 주석 앞의 종결어미만 처리한다.
    boundary = r"(?=[.!?。！？\s\)\]’'\"”]|\(|$)"

    def copula(match):
        previous = match.group(1)
        code = ord(previous)
        vowel_ending = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 == 0
        return previous + ("요" if vowel_ending else "이오")

    text = re.sub(r"([^\s])입니다" + boundary, copula, text)
    text = re.sub(r"습니다" + boundary, "소", text)

    def polite(match):
        syllable = match.group(1)
        code = ord(syllable)
        if (code - 0xAC00) % 28 == 17:  # ㅂ니다 → 모음 어간 + 오
            return chr(code - 17) + "오"
        return match.group(0)

    return re.sub(r"([가-힣])니다" + boundary, polite, text)
