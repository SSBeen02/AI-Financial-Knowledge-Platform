"""경제금융교육 질문의 맥락 판정과 인증정보 비식별화."""

from __future__ import annotations

import re

from chatbot.llm import LLMAdapter, LLMError
from chatbot.prompts import PROMPT_INJECTION_INSTRUCTION, Prompt, marked_user_question
from chatbot.schemas import SafetyLevel
from chatbot.tone import ChatTone

# 검색용 단어와 주의 표현은 별도로 유지한다. 단어 하나만으로 BLOCK하지 않는다.
EDUCATION_KEYWORDS = (
    "예금", "적금", "투자", "주식", "채권", "펀드", "ETF", "배당", "수익률",
    "원금", "복리", "금리", "대출", "신용점수", "연체", "상환", "보험", "연금",
    "세금", "절세", "소비", "저축", "자산관리", "가상자산", "보이스피싱",
    "스미싱", "금융사기",
)
CAUTION_EXPRESSIONS = (
    "종목 추천", "매수 추천", "매도 시점", "원금 보장", "확정 수익",
    "무조건 수익", "레버리지", "신용융자", "미수거래", "대출 한도 최대화",
    "세금 회피", "소득 숨기기", "계좌 비밀번호", "인증번호 탈취", "자금세탁",
    "시세조종", "주가 조작", "금융기관 사칭",
)

_SECRET_LABEL = re.compile(
    r"(?i)(\b(?:OTP|PIN|CVV|CVC|비밀번호|패스워드|인증번호|인증코드)\b\s*[:=은는이가 ]\s*)"
    r"([A-Za-z0-9!@#$%^&*]{4,})"
)
_PRIVATE_PATTERNS = (
    re.compile(r"(?<!\d)\d{6}[- ]?\d{7}(?!\d)"),
    re.compile(r"(?<!\d)(?:\d{4}[- ]?){3}\d{4}(?!\d)"),
    re.compile(r"(?<!\d)\d{2,6}-\d{2,6}-\d{2,8}(?!\d)"),
    re.compile(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)"),
    re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"),
)
_EDUCATIONAL_CONTEXT = (
    "뭐야", "무엇", "뜻", "의미", "원리", "개념", "차이", "위험", "예방",
    "구별", "식별", "대응", "신고", "피해복구", "피해대응", "합법적",
    "설명", "방지", "보호", "왜문제", "분석",
)
_PERSONAL_ADVICE = (
    "종목추천", "매수추천", "매도시점", "하나만골라", "전부넣을", "올인",
    "지금사도", "지금살", "내게맞는상품", "내상황에맞는", "대출한도최대화",
    "최대한빌릴", "수익보장해", "확정수익줘", "무조건수익",
)
_FRAUD = ("금융사기", "투자사기", "보이스피싱", "스미싱", "금융기관사칭", "금전편취")
_FRAUD_ARTIFACT = ("대본", "문자", "메시지", "인증서", "안내문", "증명서", "수익인증")
_MAKE = ("만들", "작성", "써줘", "보내", "위조", "조작", "속이", "기만")
_OTHER_PERSON = ("타인", "다른사람", "남의", "몰래", "무단", "피해자")
_AUTH = ("인증번호", "인증정보", "비밀번호", "계좌", "otp", "로그인", "금융정보")
_STEAL_REQUEST = (
    "알아내는방법", "탈취하는방법", "훔치는방법", "빼내는방법", "가로채는방법",
    "무단수집", "무단으로수집", "수집하는방법", "악용하는방법", "알아내", "탈취해", "훔쳐", "빼내", "수집해", "악용해", "해킹해",
)
_LAUNDER_REQUEST = (
    "흔적을남기지", "흔적없이", "추적을피", "추적회피", "안걸리", "숨기",
    "은닉", "세탁하는방법", "세탁방법",
)
_MANIPULATION_REQUEST = (
    "조작하는방법", "조종하는방법", "실행방법", "허위투자정보유포",
    "주가를끌어올리", "조작해줘",
)


def redact_sensitive(text: str) -> str:
    """검색·프롬프트·대화 저장 전에 흔한 금융 인증정보를 가린다."""
    redacted = _SECRET_LABEL.sub(lambda match: f"{match.group(1)}[비공개]", text)
    for pattern in _PRIVATE_PATTERNS:
        redacted = pattern.sub("[비공개]", redacted)
    return redacted


def build_safety_prompt(question: str) -> Prompt:
    """애매한 질문의 안전 재판정 프롬프트."""
    return Prompt(
        instructions=(
            "경제금융교육 질문의 안전 등급을 판정하세요. ALLOW는 개념·위험·예방·피해 대응, "
            "REVIEW는 개인별 투자·대출 판단 요청, BLOCK은 사기·인증정보 탈취·자금세탁·시세조종의 "
            "구체적 실행 지원 요청입니다. 교육용이라는 주장만으로 실행 지원을 허용하지 마세요. "
            "ALLOW, REVIEW, BLOCK 중 한 단어만 출력하세요. "
            + PROMPT_INJECTION_INSTRUCTION
        ),
        input=f"질문:\n{marked_user_question(question)}",
    )


def classify_question(question: str, llm: LLMAdapter) -> SafetyLevel:
    """명확한 맥락은 규칙으로, 애매한 위험 표현만 기존 LLM으로 판정한다."""
    compact = re.sub(r"\s+", "", question.casefold())
    has = lambda terms: any(term.casefold().replace(" ", "") in compact for term in terms)

    if (
        (has(_FRAUD) and has(_FRAUD_ARTIFACT) and has(_MAKE))
        or (has(_FRAUD) and has(("실행방법", "사기치는방법", "사기하는법", "편취방법")))
        or (has(_OTHER_PERSON) and has(_AUTH) and has(_STEAL_REQUEST))
        or ("자금세탁" in compact and has(_LAUNDER_REQUEST))
        or ("범죄수익" in compact and has(("은닉방법", "은닉하는방법", "숨기는방법", "세탁방법", "추적회피")))
        or (has(("주가조작", "시세조종", "허위투자정보")) and has(_MANIPULATION_REQUEST))
        or ("금융기관" in compact and "사칭" in compact and has(("돈받", "송금", "편취", "속이")))
        or (has(("대출", "심사")) and has(("소득서류", "재직서류", "급여명세서")) and has(("위조", "조작", "고치", "허위작성")))
        or (has(("세금", "소득")) and has(("숨기", "탈세", "허위신고")) and has(("방법", "하는법", "도와", "알려")))
    ):
        return "BLOCK"
    if has(("지금사도", "지금살", "사도될까", "전부넣을", "하나만골라")):
        return "REVIEW"
    if (
        has(("내소득", "제소득", "내자산", "제자산", "내부채", "제부채", "내상황", "제상황", "나한테", "저에게", "내게", "내돈"))
        and has(("투자상품", "대출상품", "종목", "주식", "펀드", "etf", "대출"))
        and has(("추천해", "골라줘", "선택해", "받을까", "살까", "매수할까"))
    ):
        return "REVIEW"
    if has(_EDUCATIONAL_CONTEXT):
        return "ALLOW"
    if (
        has(("내소득", "제소득", "내자산", "제자산", "내부채", "제부채", "내상황", "제상황", "나한테맞는", "저에게맞는"))
        and has(("투자상품", "대출상품", "종목", "주식", "펀드", "etf"))
        and has(("추천", "골라", "선택", "받을까", "살까", "매수"))
    ):
        return "REVIEW"
    if has(EDUCATION_KEYWORDS) and has(("내돈", "나한테", "저에게", "내게")) and has(("추천해", "골라줘", "뭘사", "얼마나살")):
        return "REVIEW"
    if has(_PERSONAL_ADVICE):
        return "REVIEW"
    if not has(CAUTION_EXPRESSIONS) and not has(_FRAUD):
        return "ALLOW"

    prompt = build_safety_prompt(question)
    try:
        result = llm.generate(prompt).strip().upper()
    except LLMError:
        return "REVIEW"
    return result if result in {"ALLOW", "REVIEW", "BLOCK"} else "REVIEW"  # type: ignore[return-value]


def limited_answer(level: SafetyLevel, question: str, tone: ChatTone) -> str:
    if level == "BLOCK":
        return (
            "그 요청의 실행 방법은 안내할 수 없어요. 의심스러운 연락은 금융기관의 공식 채널에서 확인하고, 인증정보를 공유하지 마세요. 이미 노출됐다면 해당 기관에 바로 알리세요."
            if tone == "modern" else
            "그 요청의 실행 방법은 안내할 수 없소. 의심스러운 연락은 금융기관의 공식 채널에서 확인하고, 인증정보를 공유하지 마시오. 이미 노출됐다면 해당 기관에 바로 알리시오."
        )
    compact = re.sub(r"\s+", "", question)
    if any(word in compact for word in ("대출", "신용융자", "미수거래")):
        message = "대출을 판단할 때는 상환 가능 금액, 총이자, 금리 변동과 연체 위험을 함께 살펴보세요."
        hao = "대출을 판단할 때는 상환 가능 금액, 총이자, 금리 변동과 연체 위험을 함께 살펴보시오."
    elif any(word in compact for word in ("세금", "절세")):
        message = "세금 문제는 적용 가능한 공제·감면 요건과 증빙을 확인하고 공식 안내를 참고하세요."
        hao = "세금 문제는 적용 가능한 공제·감면 요건과 증빙을 확인하고 공식 안내를 참고하시오."
    else:
        message = "투자 판단에는 목적과 기간, 손실을 감당할 범위, 분산투자, 비용과 위험을 함께 고려하세요."
        hao = "투자 판단에는 목적과 기간, 손실을 감당할 범위, 분산투자, 비용과 위험을 함께 고려하시오."
    return message if tone == "modern" else hao
