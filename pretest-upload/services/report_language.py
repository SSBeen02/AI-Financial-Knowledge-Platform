"""사전테스트 리포트의 사용자용 서술을 검증한다."""
import re
import unicodedata

from schemas.llm_report import LlmReportAnalysis
from services.errors import LlmReportError


KOREAN_REPORT_PROMPT = (
    "사용자에게 보이는 제목과 설명은 모두 한국어 하오체로 작성하시오. "
    "영어·일본어·중국어 등 외국어 문장이나 인용문을 넣지 마시오. "
    "GDP, CPI, ETF처럼 문항에 쓰인 공식 약어와 고유 용어는 필요한 경우에만 그대로 쓰시오."
)

_HANGUL = re.compile(r"[가-힣ᄀ-ᇿㄱ-ㆎ]")
_TERMS = re.compile(
    r"(?<![A-Za-z0-9])(?:Generalized System of Preferences|Value at Risk|"
    r"World Bank|Working Poor|Glass Ceiling|Glass Wall|Glass Cliff|Bamboo Ceiling|"
    r"Gentrification|Offshoring|Reshoring|Nearshoring|Friendshoring|Stage[1-4]|"
    r"AI|CPI|DINK|EPS|ETF|EU|FTA|GATT|GDP|GNI|GNP|GSP|IMF|IoT|MFN|MMF|NEET|"
    r"NIMBY|NNI|OECD|PBR|PER|PPI|ROE|UN|VaR|VC|WTO)(?![A-Za-z0-9])"
)


def validate_report_language(report: LlmReportAnalysis) -> None:
    narratives = [report.level_diagnosis.summary, report.wrong_answer_analysis.summary]
    narratives.extend(item.diagnosis for item in report.level_diagnosis.domain_comments)
    narratives.extend(item.vulnerability for item in report.wrong_answer_analysis.items)
    for item in report.recommendations:
        narratives.extend((item.focus, item.guide))

    for narrative in narratives:
        normalized = unicodedata.normalize("NFKC", narrative)
        remaining = _TERMS.sub("", normalized)
        if not _HANGUL.search(remaining) or any(
            (char.isalpha() and not _HANGUL.fullmatch(char))
            or unicodedata.category(char).startswith("M")
            for char in remaining
        ):
            raise LlmReportError("리포트 설명은 한국어로 작성해야 하오.")
