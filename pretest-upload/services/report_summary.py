"""Add deterministic stage-score facts to report introductions."""
from math import floor

from schemas.llm_report import LlmReportAnalysis

# 화면의 영역별 스테이지 표기. 학습 상태나 스테이지 배정을 변경하지 않는다.
REPORT_STAGE_ORDER = {
    "socioeconomic_phenomena_consumer_life": 1,
    "finance_investment": 2,
    "macroeconomy_monetary_fiscal_policy": 3,
    "international_economy_industry_technology": 4,
}


def add_lowest_stage_summary(report: LlmReportAnalysis, domain_scores: list[dict]) -> LlmReportAnalysis:
    if not domain_scores:
        return report
    lowest = min(row["score"] for row in domain_scores)
    rows = sorted(
        (row for row in domain_scores if row["score"] == lowest),
        key=lambda row: REPORT_STAGE_ORDER.get(row["domain"], 99),
    )
    labels = []
    for row in rows:
        stage = REPORT_STAGE_ORDER.get(row["domain"])
        label = row["domain_label"]
        labels.append(f"Stage{stage} {label}" if stage else label)
    names = ", ".join(labels)
    score = floor(lowest + 0.5)  # 화면의 Math.round와 동일한 정수 점수 표시
    if lowest == 100:
        fact = f"{names} 모두 100점이며, 오답은 없소."
    elif len(rows) == 1:
        fact = f"이번 테스트에서 가장 낮은 점수는 {names}의 {score}점이오."
    else:
        fact = f"공동 최저점 스테이지는 {names}이며, 점수는 {score}점이오."
    result = report.model_copy(deep=True)
    for section in (result.level_diagnosis, result.wrong_answer_analysis):
        text = section.summary.strip()
        if not text.startswith(fact):
            section.summary = f"{fact} {text}".strip()
    return result
