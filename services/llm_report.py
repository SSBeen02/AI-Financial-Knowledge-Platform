import json
import logging

from database.settings import load_settings
from schemas.llm_report import (
    DomainLevelComment,
    LevelDiagnosis,
    LlmReportAnalysis,
    RecommendationItem,
    WrongAnswerAnalysis,
    WrongAnswerItem,
)
from services.domains import recommendation_for
from services.errors import LlmReportError

logger = logging.getLogger("diagnostics")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

SYSTEM_PROMPT = """당신은 경제 문해력 사전테스트를 마친 학습자에게 결과를 설명하는 상담 선생님입니다.
입력 JSON의 점수와 오답만 근거로 한국어 리포트를 작성합니다.
말투는 따뜻하고 차근차근합니다. 점수를 판정하는 짧은 문장으로 끝내지 말고, 그 결과가 무엇을 뜻하는지 풀어서 알려 주세요.
잘한 점이 있으면 먼저 인정하고, 이어서 어디를 더 보면 좋은지 안내합니다.
"시급합니다", "심각합니다", "미흡합니다"처럼 몰아붙이는 말은 쓰지 않습니다.
"~입니다", "~하면 도움이 됩니다"처럼 옆에서 설명하는 문장으로 씁니다.

구성은 바꾸지 않습니다. level_diagnosis, wrong_answer_analysis, recommendations 세 부분만 작성합니다.
- level_diagnosis.overall_level은 입력 summary.level과 같게 둡니다. 다른 레벨 이름은 만들지 않습니다.
- summary는 전체 결과를 학습자에게 말하듯 두세 문장으로 씁니다. 총점이 의미하는 바와 다음에 이어가면 좋은 방향을 함께 적습니다.
- domain_comments는 입력 domain_scores의 영역을 빠짐없이 다룹니다. score는 입력 점수를 그대로 씁니다.
- diagnosis는 점수를 반복하는 데 그치지 말고, 그 영역에서 무엇을 이해하고 있고 무엇을 더 보면 좋은지 두 문장으로 씁니다.
- wrong_answer_analysis.items의 question_id와 concept는 입력 wrong_answers에 있는 값만 사용합니다.
- vulnerability는 어떤 점을 헷갈렸는지 쉽게 풀어 줍니다. 개념 이름을 꾸짖지 않습니다.
- 틀린 문항이 없으면 items는 빈 배열로 두고, summary에는 틀린 문제가 없어서 지금 이해를 이어가면 된다고 적습니다.
- recommendations는 취약 영역(is_vulnerable가 true)을 점수가 낮은 순으로 priority 1부터 둡니다.
- focus는 이번 학습에서 보면 좋은 주제를 부드럽게 적습니다.
- guide는 실천 순서입니다. "1단계로는 ~을 살펴보면 도움이 됩니다"처럼 다음 행동을 안내합니다.
- 취약 영역이 없으면 가장 점수가 낮은 영역의 수준을 이어가는 제안을 한 항목만 작성합니다.
- 입력에 없는 개념, 점수, 문항을 만들지 않습니다.
"""


def describe_llm_mode() -> str:
    settings = load_settings()
    mode = _resolved_mode(settings)
    if mode == "local":
        return "local"
    if mode == "gemini":
        return f"gemini:{settings.gemini_model}"
    return f"openai:{settings.openai_model}"


def generate_llm_report(graded: dict) -> LlmReportAnalysis:
    """채점 결과를 구조화된 맞춤 리포트로 바꿉니다."""
    settings = load_settings()
    mode = _resolved_mode(settings)
    if mode == "local":
        return generate_local_report(graded)
    from openai import OpenAI

    if mode == "gemini":
        if not settings.gemini_api_key:
            raise LlmReportError("GEMINI_API_KEY가 없어 맞춤 리포트를 생성하지 못했습니다.")
        with OpenAI(api_key=settings.gemini_api_key, base_url=GEMINI_BASE_URL, timeout=60.0, max_retries=1) as client:
            return generate_openai_report(client, graded, settings.gemini_model, provider="Gemini")
    if not settings.openai_api_key:
        raise LlmReportError("OPENAI_API_KEY가 없어 맞춤 리포트를 생성하지 못했습니다.")
    with OpenAI(api_key=settings.openai_api_key, timeout=60.0, max_retries=1) as client:
        return generate_openai_report(client, graded, settings.openai_model, provider="OpenAI")


def generate_openai_report(client, graded: dict, model: str, provider: str = "OpenAI") -> LlmReportAnalysis:
    """OpenAI structured output으로 리포트를 받고, 점수와 오답 목록은 채점 결과에 맞춥니다."""
    payload = build_llm_input(graded)
    try:
        completion = client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False),
                },
            ],
            response_format=LlmReportAnalysis,
        )
    except LlmReportError:
        raise
    except Exception as exc:
        logger.exception("%s 리포트 생성 실패", provider)
        raise LlmReportError(
            f"맞춤 리포트를 생성하지 못했습니다. {provider} 응답을 확인해 주세요."
        ) from exc

    if not completion.choices:
        raise LlmReportError("LLM 응답에 생성 결과가 없습니다.")
    message = completion.choices[0].message
    if getattr(message, "refusal", None):
        raise LlmReportError("LLM이 리포트 생성을 거절했습니다.")
    parsed = getattr(message, "parsed", None)
    if not isinstance(parsed, LlmReportAnalysis):
        raise LlmReportError("LLM 응답을 구조화된 리포트로 읽지 못했습니다.")
    return align_llm_report(parsed, graded)


def generate_local_report(graded: dict) -> LlmReportAnalysis:
    """API 키가 없을 때 같은 스키마의 초안을 만듭니다. 문장은 채점 결과에서 조립합니다."""
    summary = graded["summary"]
    draft = LlmReportAnalysis(
        level_diagnosis=LevelDiagnosis(
            overall_level=summary["level"],
            summary=summary["analysis"],
            domain_comments=[],
        ),
        wrong_answer_analysis=WrongAnswerAnalysis(summary="", items=[]),
        recommendations=[],
    )
    return align_llm_report(draft, graded)


def build_llm_input(graded: dict) -> dict:
    summary = graded["summary"]
    wrong_answers = []
    for item in graded["question_results"]:
        if item["is_correct"]:
            continue
        wrong_answers.append(
            {
                "question_id": item["question_id"],
                "domain": item["domain"],
                "domain_label": item["domain_label"],
                "concept": item["concept"],
                "difficulty": item["difficulty"],
                "question": item["question"],
                "options": item["options"],
                "selected_option": item["options"][item["selected_answer"] - 1],
                "correct_option": item["options"][item["correct_answer"] - 1],
                "selected_answer": item["selected_answer"],
                "correct_answer": item["correct_answer"],
                "explanation": item["explanation"]["correct"],
            }
        )
    return {
        "summary": {
            "score": summary["score"],
            "level": summary["level"],
            "correct_count": summary["correct_count"],
            "total_questions": summary["total_questions"],
            "vulnerable_threshold": summary["vulnerable_threshold"],
        },
        "domain_scores": [
            {
                "domain": row["domain"],
                "domain_label": row["domain_label"],
                "score": row["score"],
                "correct_count": row["correct_count"],
                "total_questions": row["total_questions"],
                "is_vulnerable": row["is_vulnerable"],
            }
            for row in graded["domain_scores"]
        ],
        "wrong_answers": wrong_answers,
    }


def align_llm_report(report: LlmReportAnalysis, graded: dict) -> LlmReportAnalysis:
    """점수와 수준은 채점값을 유지하고 LLM이 쓴 문장만 가져옵니다."""
    summary = graded["summary"]
    domain_scores = graded["domain_scores"]
    wrong = [item for item in graded["question_results"] if not item["is_correct"]]
    comments = {item.domain: item for item in report.level_diagnosis.domain_comments}
    analysis_items = {item.question_id: item for item in report.wrong_answer_analysis.items}

    domain_comments = []
    for row in domain_scores:
        existing = comments.get(row["domain"])
        diagnosis = existing.diagnosis.strip() if existing and existing.diagnosis.strip() else _domain_diagnosis(row)
        domain_comments.append(
            DomainLevelComment(
                domain=row["domain"],
                domain_label=row["domain_label"],
                score=row["score"],
                diagnosis=diagnosis,
            )
        )

    wrong_items = []
    for item in wrong:
        existing = analysis_items.get(item["question_id"])
        vulnerability = (
            existing.vulnerability.strip()
            if existing and existing.vulnerability.strip()
            else (
                f"{item['concept']}은 비슷한 말과 헷갈리기 쉬운 개념입니다. "
                "뜻의 차이만 다시 구분해 보면 다음번에는 고르기 쉬워집니다."
            )
        )
        wrong_items.append(
            WrongAnswerItem(
                question_id=item["question_id"],
                concept=item["concept"],
                domain=item["domain"],
                domain_label=item["domain_label"],
                vulnerability=vulnerability,
            )
        )

    level_summary = report.level_diagnosis.summary.strip() or summary["analysis"]
    if wrong:
        wrong_summary = report.wrong_answer_analysis.summary.strip() or f"틀린 문항은 {len(wrong)}개입니다."
    else:
        wrong_summary = report.wrong_answer_analysis.summary.strip() or "틀린 문항이 없습니다."

    return LlmReportAnalysis(
        level_diagnosis=LevelDiagnosis(
            overall_level=summary["level"],
            summary=level_summary,
            domain_comments=domain_comments,
        ),
        wrong_answer_analysis=WrongAnswerAnalysis(summary=wrong_summary, items=wrong_items),
        recommendations=_align_recommendations(report.recommendations, domain_scores, wrong),
    )


def _resolved_mode(settings) -> str:
    mode = settings.llm_report_mode
    if mode not in {"auto", "openai", "gemini", "local"}:
        raise LlmReportError("LLM_REPORT_MODE는 auto, openai, gemini, local 중 하나여야 합니다.")
    if mode == "local":
        return "local"
    if mode == "openai":
        return "openai"
    if mode == "gemini":
        return "gemini"
    if settings.gemini_api_key:
        return "gemini"
    if settings.openai_api_key:
        return "openai"
    return "local"


def _domain_diagnosis(row: dict) -> str:
    if row["is_vulnerable"]:
        return (
            f"{row['domain_label']}은 이번 점수로는 기초를 조금 더 채우면 좋은 영역입니다. "
            "틀린 개념부터 차근차근 다시 보면 도움이 됩니다."
        )
    return (
        f"{row['domain_label']}은 이번 진단에서 기준을 넘겼습니다. "
        "이해한 내용을 비슷한 사례에 한 번 더 적용해 보면 좋습니다."
    )


def _align_recommendations(
    items: list[RecommendationItem],
    domain_scores: list[dict],
    wrong: list[dict],
) -> list[RecommendationItem]:
    guides = {}
    for item in items:
        if item.domain not in guides and item.guide.strip():
            guides[item.domain] = item

    vulnerable = sorted(
        (row for row in domain_scores if row["is_vulnerable"]),
        key=lambda row: row["score"],
    )
    if not vulnerable and domain_scores:
        vulnerable = [min(domain_scores, key=lambda row: row["score"])]
        maintain = True
    else:
        maintain = not any(row["is_vulnerable"] for row in domain_scores)

    recommendations = []
    for index, row in enumerate(vulnerable, start=1):
        existing = guides.get(row["domain"])
        missed = [item["concept"] for item in wrong if item["domain"] == row["domain"]]
        if existing and existing.guide.strip():
            guide = existing.guide.strip()
            focus = existing.focus.strip() or row["domain_label"]
        elif maintain:
            focus = "현재 수준 유지"
            guide = f"{row['domain_label']} 해설을 한 번 더 읽고, 비슷해 보이는 개념의 차이를 정리해 보세요."
        else:
            focus = f"{row['domain_label']} 보완"
            guide = recommendation_for(row["domain"], missed)
        recommendations.append(
            RecommendationItem(
                priority=index,
                domain=row["domain"],
                domain_label=row["domain_label"],
                focus=focus,
                guide=guide,
            )
        )
    return recommendations
