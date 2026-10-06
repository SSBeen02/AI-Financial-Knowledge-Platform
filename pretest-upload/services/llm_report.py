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
from services.errors import LlmReportError

logger = logging.getLogger("diagnostics")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

from services.report_parallel import STYLE_PROMPT
SYSTEM_PROMPT = STYLE_PROMPT + """\n기존 JSON 구조를 유지하시오. 등급·점수·문항 ID는 입력과 일치시켜야 하오. 총평은 2문장, 영역 진단은 1~2문장, 오답 분석은 실제 선택과 정답의 차이 및 단서를 2문장으로 설명하시오. 학습 권장은 낮은 점수부터 동점이면 입력 영역 순서로 두고, 취약 영역이 없으면 첫 최저점 영역의 유지 방향 하나만 두시오."""



def describe_llm_mode() -> str:
    settings = load_settings()
    mode = _resolved_mode(settings)
    if mode == "local":
        return "local"
    if mode == "gemini":
        return f"gemini:{settings.gemini_model}"
    return f"openai:{settings.openai_model}"


def generate_llm_report(graded: dict, *, budget: float = 28.0) -> LlmReportAnalysis:
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
    from services.report_parallel import generate_parallel_report, REPORT_BUDGET_SECONDS
    with OpenAI(api_key=settings.openai_api_key, timeout=min(budget, REPORT_BUDGET_SECONDS), max_retries=0) as client:
        return generate_parallel_report(client, graded, settings.openai_model, budget=min(budget, REPORT_BUDGET_SECONDS))


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
            summary=_haoche(summary["analysis"]),
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
                "selected_option_explanation": _option_explanation(item, item["selected_answer"]),
                "correct_option_explanation": _option_explanation(item, item["correct_answer"]),
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
                "tested_concepts": [item["concept"] for item in graded["question_results"] if item["domain"] == row["domain"]],
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
            else _wrong_answer_hint(item)
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

    level_summary = report.level_diagnosis.summary.strip() or _haoche(summary["analysis"])
    if wrong:
        wrong_summary = report.wrong_answer_analysis.summary.strip() or f"틀린 문항은 {len(wrong)}개이오."
    else:
        wrong_summary = report.wrong_answer_analysis.summary.strip() or "틀린 문항이 없습니다."

    return LlmReportAnalysis(
        level_diagnosis=LevelDiagnosis(
            overall_level=summary["level"],
            summary=level_summary,
            domain_comments=domain_comments,
        ),
        wrong_answer_analysis=WrongAnswerAnalysis(summary=wrong_summary, items=wrong_items),
        recommendations=_align_recommendations(report.recommendations, domain_scores, wrong, graded["question_results"]),
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
    total = row["total_questions"]
    correct = row["correct_count"]
    if correct == total:
        return f"이번 영역의 {total}문항을 모두 맞혔소. 이 문항에서 확인한 개념을 정확히 구분했소."
    return f"이번 영역의 {total}문항 중 {correct}문항을 맞혔습니다. 아래 오답에서 선택한 보기와 정답의 차이를 확인해 보세요."


def _align_recommendations(
    items: list[RecommendationItem],
    domain_scores: list[dict],
    wrong: list[dict],
    question_results: list[dict] | None = None,
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
        if existing and existing.guide.strip():
            guide = existing.guide.strip()
            focus = existing.focus.strip() or row["domain_label"]
        else:
            focus, guide = _study_guide(row, wrong, maintain, question_results or [])
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


def _option_explanation(item: dict, answer: int) -> str:
    details = item["explanation"].get("options_detail") or []
    # 이전 기록의 해설이 일부만 있을 때 다른 보기의 해설을 붙이지 않는다.
    if len(details) != len(item["options"]):
        return ""
    return details[answer - 1]



def _wrong_answer_hint(item: dict) -> str:
    selected = item["options"][item["selected_answer"] - 1].partition(")")[2].strip() or item["options"][item["selected_answer"] - 1]
    correct = item["options"][item["correct_answer"] - 1].partition(")")[2].strip() or item["options"][item["correct_answer"] - 1]
    return f"선택한 답은 {selected}, 정답은 {correct}이오. {_haoche(item['explanation']['correct'])}"


def _study_guide(row: dict, wrong: list[dict], maintain: bool, question_results: list[dict]) -> tuple[str, str]:
    """모델 설명이 없을 때 실제 보기와 해설로 한 문단을 구성합니다."""
    source = [item for item in (question_results if maintain else wrong) if item["domain"] == row["domain"]]
    focus = f"{row['domain_label']} 개념 구분과 접근"
    if not source:
        return focus, f"{row['domain_label']}의 이번 결과는 출제된 문항 범위에서 해석할 수 있소. 개념을 구분할 때는 이름보다 적용 대상과 조건이 기준이 되오. 문제에 제시된 단서와 보기의 조건을 연결하는 접근이 유용하오."
    item = source[0]
    concept = item["concept"]
    correct = item["options"][item["correct_answer"] - 1]
    selected = item["options"][item["selected_answer"] - 1]
    opening = f"{concept}에서는 이번 문항의 정답인 {correct}를 판단하는 기준을 유지하는 것이 핵심입니다." if maintain else f"{concept}에서는 선택한 {selected}와 정답인 {correct}의 구분 기준을 중심으로 보완할 수 있습니다."
    explanation = item["explanation"]["correct"].strip()
    if explanation and explanation[-1] not in ".!?。":
        explanation += "."
    ending = f"{concept} 문제에 접근할 때는 질문의 조건이 {correct}의 설명과 맞는지를 우선 확인하는 것이 유리합니다."
    return focus, _haoche(" ".join([opening, explanation, "비슷한 이름의 보기라도 적용 대상과 성립 조건이 같지는 않다는 점을 구분해두어야 합니다.", ending]))




def _haoche(text: str) -> str:
    """Convert only trusted local fallback text, never rewrite a model's narrative."""
    replacements = {"확인해 보세요": "살펴보시오", "좋습니다": "좋겠소", "해야 합니다": "해야 하오", "할 수 있습니다": "할 수 있소", "없습니다": "없소", "있습니다": "있소", "맞혔습니다": "맞혔소", "구분했습니다": "구분했소", "됩니다": "되오", "합니다": "하오", "입니다": "이오", "하세요": "하시오"}
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text
