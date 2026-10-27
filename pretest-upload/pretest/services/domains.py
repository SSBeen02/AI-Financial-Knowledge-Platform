VULNERABLE_SCORE_THRESHOLD = 70.0
HIGH_SEVERITY_SCORE_THRESHOLD = 50.0

DOMAIN_CATALOG: dict[str, dict[str, str]] = {
    "finance_investment": {
        "label": "금융·투자",
        "recommendation": (
            "단리·복리, 연금제도, 예금자보호, ETF, PER, VaR를 중심으로 "
            "금융·투자 기초 개념을 다시 정리해 보세요."
        ),
    },
    "macroeconomy_monetary_fiscal_policy": {
        "label": "거시경제·통화·재정",
        "recommendation": (
            "물가지수, 기준금리, 세금, GDP, 고용지표, 국가채무의 정의와 "
            "비슷해 보이는 지표의 차이를 비교해 보세요."
        ),
    },
    "international_economy_industry_technology": {
        "label": "국제경제·산업·기술",
        "recommendation": (
            "FTA, WTO, 4차 산업혁명, 리쇼어링, 벤처캐피탈, GSP처럼 "
            "제도와 산업 용어가 가리키는 범위를 구분해 보세요."
        ),
    },
    "socioeconomic_phenomena_consumer_life": {
        "label": "사회경제·소비생활",
        "recommendation": (
            "고령화 구분, 청년 고용, 근로빈곤, 도시 변화, 직장 내 장벽, "
            "은퇴 소득공백 개념을 유사 용어와 짝지어 정리해 보세요."
        ),
    },
}


def domain_label(domain: str) -> str:
    return DOMAIN_CATALOG.get(domain, {}).get("label", domain)


def recommendation_for(domain: str, missed_concepts: list[str]) -> str:
    base = DOMAIN_CATALOG.get(domain, {}).get(
        "recommendation",
        "틀린 문항의 해설을 보고 핵심 개념을 다시 확인해 주세요.",
    )
    if not missed_concepts:
        return base
    return f"{base} 이번 진단에서 틀린 개념은 {', '.join(missed_concepts)}입니다."


def level_for(score: float) -> str:
    if score >= 90:
        return "우수"
    if score >= 75:
        return "양호"
    if score >= 60:
        return "보통"
    return "보완필요"


def percent_score(correct: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(correct * 100 / total, 1)


def format_score(score: float) -> str:
    if score == int(score):
        return str(int(score))
    return str(score)
