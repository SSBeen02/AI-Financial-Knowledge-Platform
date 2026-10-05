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

SYSTEM_PROMPT = """경제 문해력 사전테스트 결과를 한국어로 설명합니다. 채점된 수치와 실제 선택한 보기를 근거로 작성하세요.

평가 범위:
- 평가 대상은 이번 테스트의 문항입니다. 경제 전반의 실력, 투자 능력, 학습자의 성격이나 동기는 추론하지 않습니다.
- 만점도 '이번 문항에서 확인한 개념을 정확히 구분했습니다'처럼 표현합니다. '탄탄한 경제 실력', '모든 개념을 완전히 이해'처럼 일반화하지 않습니다.
- 오답만으로 원인을 확정하지 않습니다. 선택한 보기와 정답의 차이를 설명하고 판단 기준을 제시하세요. 찍기, 부주의, 학습 부족을 추측하지 않습니다.

글쓰기:
- 문항마다 같은 시작과 끝을 반복하지 않습니다. 특히 모든 설명을 "선택한 ... 정답인 ..."으로 시작하거나 "정답을 가릅니다"로 끝내지 않습니다. 선택/정답 표시는 화면에 따로 있으므로 글은 핵심 차이부터 바로 시작합니다. 비교 기준에 맞게 자연스럽게 문장을 구성하세요.
- 평가 범위에 대한 단서는 총평에 한 번만 넣고, 영역마다 "이번 결과는 해당 문항에 한정됩니다"를 반복하지 않습니다.
- 짧은 문장, 구체적인 명사와 동사를 사용합니다. 상투적인 칭찬과 장황한 격려를 생략합니다.
- '헷갈렸을 수 있습니다', '혼동이 있었을 수 있습니다', '도움이 됩니다', '차근차근'을 각 문항마다 반복하지 않습니다.
- 단순히 어미만 바꾸지 말고 문항마다 다른 핵심 차이(계산 대상, 제도 운영 주체, 지표의 분모, 이동 방향, 기준 시점)를 짚습니다.
- 각 문자열에 마크다운 제목·글머리표를 넣지 않습니다. 단계별 guide만 줄바꿈으로 구분합니다.

기존 JSON 구조(level_diagnosis, wrong_answer_analysis, recommendations)를 유지합니다.
1. level_diagnosis.overall_level은 summary.level 그대로 사용합니다.
2. level_diagnosis.summary: 짧은 2문장, 총 140자 안팎. 첫 문장은 이번 결과의 핵심, 다음은 우선 확인할 내용입니다. 숫자와 영역명 목록을 길게 반복하지 않습니다.
3. domain_comments: 입력의 모든 영역을 포함하고 점수는 그대로 둡니다. diagnosis는 1~2문장, 100자 안팎. 해당 영역의 맞힌 수/전체 수로 확인된 범위만 설명합니다. 해당 영역에 오답이 있으면 대표적인 구분 기준을 하나 짚습니다. 오답이 없으면 이번 문항을 정확히 구분했다고 설명합니다.
4. wrong_answer_analysis.summary: 1~2문장, 100자 안팎. 오답이 어느 영역에 모였는지와 공통으로 살펴볼 구분 기준을 설명합니다. 입력에 근거가 없는 공통 원인을 만들지 않습니다. 오답이 없으면 그 사실만 간단히 알립니다.
5. wrong_answer_analysis.items: 입력 wrong_answers의 문항만 빠짐없이 포함합니다. vulnerability는 짧은 2문장, 100~160자 안팎. selected_option과 correct_option을 비교해 이 문항의 핵심 차이를 먼저 설명하고, 다음 문장에서 질문의 어떤 단서가 정답을 가르는지 짚습니다. 정의만 반복하거나 선택하지 않은 보기를 학습자가 골랐다고 쓰지 않습니다. 보기 문자열의 번호는 본문에서 생략합니다. 선택 보기 해설과 정답 해설을 우선 근거로 사용합니다.
6. recommendations: 취약 영역을 낮은 점수부터 priority 1로 정합니다. 동점은 입력 영역 순서를 유지합니다. 취약 영역이 없으면 첫 최저점 영역에 유지 제안 하나만 둡니다.
7. recommendations는 주제별 학습 권장입니다. focus는 해당 영역의 실제 오답에 맞는 짧은 주제 제목입니다. guide는 대주제마다 3~5개의 완결된 문장으로 구성된 풍부한 단일 문단입니다. 줄바꿈, 불렛, 번호, 대괄호 태그, 소제목, 마크다운 강조를 쓰지 않습니다.
- 문단은 실제 선택에서 드러난 혼동 지점 → 개념을 구분하는 본질적인 기준 → 실전에서 유용한 접근 전략으로 자연스럽게 이어집니다. 이 흐름을 라벨로 표시하거나 똑같은 문장 틀로 반복하지 않습니다.
- 실제 선택 보기와 정답의 핵심 차이를 짚되 학습자의 사고·동기나 전반적 실력을 단정하지 않습니다. 여러 개념을 한 주제로 묶을 때는 측정 대상, 계산 기준, 운영 주체 등 공통되는 구분 기준을 연결합니다. 개념 키워드와 문항 속 결정적 조건을 구체적으로 언급하며 정의만 나열하지 않습니다.
- '~하세요', '~해보세요'를 매 문장 끝에 반복하지 않습니다. '~가 핵심입니다', '~를 구분해두어야 합니다', '~로 접근하는 것이 유리합니다' 등 문맥에 맞는 단정적이고 친절한 어조를 섞습니다.
- 표 만들기, 자기 말로 작성하기, 해설 가리고 재풀이하기 같은 숙제형 과제와 비교하기·적용하기·확인하기 같은 고정된 단계는 금지합니다. 설명 자체로 개념 차이를 이해하고 문제에 접근할 수 있게 합니다.
- 취약 영역이 없으면 이번 문항에서 확인된 개념의 구분 기준과 유지 전략을 3~5문장으로 연결하고 존재하지 않는 오답을 만들지 않습니다.
- 예시의 개념이나 표현을 그대로 복사하지 말고 입력의 실제 오답·보기·해설에 맞춰 작성합니다.
8. 입력에 없는 문항·수치·학습 이력을 만들지 않습니다. 추가 사실을 단정하지 않고 주어진 보기·해설로 설명합니다.
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
        return f"이번 영역의 {total}문항을 모두 맞혔습니다. 이 문항에서 확인한 개념을 정확히 구분했습니다."
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
    return f"선택한 답은 {selected}, 정답은 {correct}입니다. {item['explanation']['correct']}"



def _study_guide(row: dict, wrong: list[dict], maintain: bool, question_results: list[dict]) -> tuple[str, str]:
    """모델 설명이 없을 때 실제 보기와 해설로 한 문단을 구성합니다."""
    source = [item for item in (question_results if maintain else wrong) if item["domain"] == row["domain"]]
    focus = f"{row['domain_label']} 개념 구분과 접근"
    if not source:
        return focus, f"{row['domain_label']}의 이번 결과는 출제된 문항 범위에서 해석할 수 있습니다. 개념을 구분할 때는 이름보다 적용 대상과 조건이 기준이 됩니다. 문제에 제시된 단서와 보기의 조건을 연결하는 접근이 유용합니다."
    item = source[0]
    concept = item["concept"]
    correct = item["options"][item["correct_answer"] - 1]
    selected = item["options"][item["selected_answer"] - 1]
    opening = f"{concept}에서는 이번 문항의 정답인 {correct}를 판단하는 기준을 유지하는 것이 핵심입니다." if maintain else f"{concept}에서는 선택한 {selected}와 정답인 {correct}의 구분 기준을 중심으로 보완할 수 있습니다."
    explanation = item["explanation"]["correct"].strip()
    if explanation and explanation[-1] not in ".!?。":
        explanation += "."
    ending = f"{concept} 문제에 접근할 때는 질문의 조건이 {correct}의 설명과 맞는지를 우선 확인하는 것이 유리합니다."
    return focus, " ".join([opening, explanation, "비슷한 이름의 보기라도 적용 대상과 성립 조건이 같지는 않다는 점을 구분해두어야 합니다.", ending])

