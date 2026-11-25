"""결과 리포트 서술에 적용하는 고정 하오체 규칙."""
import re

from pretest.schemas.llm_report import LlmReportAnalysis
from pretest.services.errors import LlmReportError

REPORT_TONE = "하오체"

# 긴 어미를 먼저 처리해 '해야 합니다' 등의 결합을 보존한다.
_ENDINGS = {
    "확인해 보세요": "살펴보시오",
    "좋습니다": "좋겠소",
    "바랍니다": "바라오",
    "해야 합니다": "해야 하오",
    "할 수 있습니다": "할 수 있소",
    "했습니다": "했소",
    "집니다": "지오",
    "봅니다": "보오",
    "줍니다": "주오",
    "드립니다": "드리오",
    "칩니다": "치오",
    "킵니다": "키오",
    "납니다": "나오",
    "릅니다": "르오",
    "아닙니다": "아니오",
    "아니에요": "아니오",
    "아니요": "아니오",
    "됩니다": "되오",
    "합니다": "하오",
    "입니다": "이오",
    "습니다": "소",
    "주세요": "주시오",
    "보세요": "보시오",
    "하세요": "하시오",
    "세요": "시오",
    "거예요": "것이오",
    "이에요": "이오",
    "예요": "이오",
    "했어요": "했소",
    "었어요": "었소",
    "았어요": "았소",
    "겠어요": "겠소",
    "해요": "하오",
    "돼요": "되오",
    "있어요": "있소",
    "없어요": "없소",
    "않아요": "않소",
    "같아요": "같소",
    "좋아요": "좋소",
    "맞아요": "맞소",
    "많아요": "많소",
    "높아요": "높소",
    "적어요": "적소",
    "싶어요": "싶소",
    "쉬워요": "쉽소",
    "어려워요": "어렵소",
    "달라요": "다르오",
    "커요": "크오",
    "보여요": "보이오",
    "죠": "소",
    "펀드요": "펀드라오",
    "지표요": "지표라오",
    "단서요": "단서라오",
    "금리요": "금리라오",
    "범위요": "범위라오",
    "간접세요": "간접세라오",
    "채무요": "채무라오",
}
_SENTENCE_END = r"(?=\s*(?:$|[.!?。！？…,\n\"'”’」』)]))"
_ENDING_PATTERN = re.compile(
    "(?:" + "|".join(re.escape(ending) for ending in sorted(_ENDINGS, key=len, reverse=True)) + ")" + _SENTENCE_END
)
_POLITE_ENDING = re.compile(
    r"(?:니다|니까|세요|해요|돼요|예요|이에요|아요|어요|여요|죠)" + _SENTENCE_END
)


def normalize_haoche_text(text: str) -> str:
    return _ENDING_PATTERN.sub(lambda match: _ENDINGS[match.group()], text)


def normalize_report_tone(report: LlmReportAnalysis) -> LlmReportAnalysis:
    result = report.model_copy(deep=True)
    result.level_diagnosis.summary = normalize_haoche_text(result.level_diagnosis.summary)
    result.wrong_answer_analysis.summary = normalize_haoche_text(result.wrong_answer_analysis.summary)
    for item in result.level_diagnosis.domain_comments:
        item.diagnosis = normalize_haoche_text(item.diagnosis)
    for item in result.wrong_answer_analysis.items:
        item.vulnerability = normalize_haoche_text(item.vulnerability)
    for item in result.recommendations:
        item.guide = normalize_haoche_text(item.guide)

    narratives = [result.level_diagnosis.summary, result.wrong_answer_analysis.summary]
    narratives.extend(item.diagnosis for item in result.level_diagnosis.domain_comments)
    narratives.extend(item.vulnerability for item in result.wrong_answer_analysis.items)
    narratives.extend(item.guide for item in result.recommendations)
    if any(_POLITE_ENDING.search(text) for text in narratives):
        raise LlmReportError("리포트의 하오체 문장을 확인하지 못했소. 다시 생성할 수 있소.")
    return result
