"""Language rules for quiz questions, choices and explanations."""

import re
import unicodedata


_TERMS = {
    "GDP": "국내총생산", "GNP": "국민총생산", "CPI": "소비자물가지수",
    "FTA": "자유무역협정", "ETF": "상장지수펀드", "DSR": "총부채원리금상환비율",
    "BEP": "손익분기점", "EBITDA": "이자·세금·감가상각비 차감 전 이익",
    "ROE": "자기자본이익률", "ROA": "총자산이익률", "ROI": "투자수익률",
    "NPV": "순현재가치", "IT": "정보기술", "AI": "인공지능", "IoT": "사물인터넷",
    "TV": "텔레비전", "OTT": "온라인 동영상", "PLC": "프로그램 가능 논리 제어기",
    "SWOT": "강점·약점·기회·위협", "M&A": "인수합병", "R&D": "연구개발",
    "MR": "한계수입", "MC": "한계비용", "AC": "평균비용",
    "Qd": "수요량", "Qs": "공급량", "Q": "거래량", "P": "가격",
    "A": "갑", "B": "을", "C": "병", "J": "제이",
    "4Ps": "네 가지 요소", "Product": "제품", "Price": "가격",
    "Place": "유통", "Promotion": "촉진",
}
_ENGLISH_GLOSSES = re.compile(
    r"\((?:GDP|GNP|CPI|FTA|ETF|DSR|BEP|ROE|ROA|ROI|NPV|MR|MC|"
    r"Product|Price|Place|Promotion|Finance|Technology|Acquisition|Merger|"
    r"trade-off|비용 push|M&A|S|W|O|T)\)"
)
_TERM_PATTERN = re.compile(
    r"(?<![A-Za-z])(?:" + "|".join(map(re.escape, sorted(_TERMS, key=len, reverse=True))) + r")(?![A-Za-z])"
)


def localize_quiz_text(text: str) -> str:
    """Translate known terms in fixed and previously stored questions."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace(
        "EBITDA는 Earnings Before Interest, Taxes, Depreciation and Amortization의 약자로",
        "이자·세금·감가상각비 차감 전 이익은",
    )
    text = _ENGLISH_GLOSSES.sub("", text)
    text = _TERM_PATTERN.sub(lambda match: _TERMS[match.group()], text)
    return re.sub(r"(총부채원리금상환비율|자기자본이익률|투자수익률|자유무역협정)\(\1\)", r"\1", text)


def validate_korean_text(text: str, *, allow_numeric: bool = False) -> None:
    has_hangul = False
    has_digit = False
    for char in unicodedata.normalize("NFC", text):
        name = unicodedata.name(char, "")
        if name.startswith(("HANGUL SYLLABLE ", "HANGUL LETTER ", "HANGUL CHOSEONG ",
                            "HANGUL JUNGSEONG ", "HANGUL JONGSEONG ")):
            has_hangul = True
        elif char in "0123456789":
            has_digit = True
        elif not (char.isspace() or unicodedata.category(char).startswith("P")
                  or unicodedata.category(char) in {"Sm", "Sc"}):
            raise ValueError("문제, 상황형 보기, 해설은 한글로 작성해야 합니다.")
    if not has_hangul and not (allow_numeric and has_digit):
        raise ValueError("문제, 상황형 보기, 해설에 한국어 내용이 필요합니다.")
