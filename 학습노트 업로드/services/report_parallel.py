"""Concurrent report narratives; public report facts are always assembled from grading."""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_EXCEPTION
from typing import Callable

from pydantic import BaseModel, ConfigDict
from schemas.llm_report import DomainLevelComment, LevelDiagnosis, LlmReportAnalysis, RecommendationItem, WrongAnswerAnalysis, WrongAnswerItem
from services.errors import LlmReportError

logger = logging.getLogger("diagnostics")
REPORT_BUDGET_SECONDS = 28.0
# Bound outbound concurrency across reports, not just within one report.
_API_SLOTS = threading.BoundedSemaphore(12)

STYLE_PROMPT = """경제 사전테스트의 친절한 튜터로서 입력 보기·해설·채점만 근거로 설명하시오.
모든 서술은 현대인이 읽기 쉬운 가벼운 하오체로 쓰시오. 명사 뒤는 문법에 맞게 ~이오/~라오를 쓰고 ~단서요/~펀드요처럼 일반 해요체나 어색한 축약을 쓰지 마시오. ~하오/~이오/~소/~시오/~겠소를 문맥에 맞게 섞고, 억지로 하오만 붙이거나 ~합니다/~하세요를 쓰지 마시오. 전하·소인·나으리·명심하시오·분부 등 과장된 사극 표현과 꾸짖음은 금지하오.
평가는 이번 문항 범위에 한정하되 그 단서를 영역마다 반복하지 마시오. 전반적 능력·성격·동기·오답 원인을 단정하지 마시오.
같은 문장 시작·끝, '헷갈렸을 수 있소' 같은 추측의 반복을 피하고 실제 선택과 정답의 핵심 차이 및 문제 단서를 직접 짚으시오. 숫자·기간·주체는 입력에 충실해야 하오.
대괄호 태그, 불렛, 번호, 마크다운 강조와 숙제형 지시(표 만들기·자기 말로 쓰기·해설 가리고 재풀이)를 쓰지 마시오.
recommendation은 오답 정의 나열이 아니라 이후 학습 방향과 접근 전략이오. 실제 혼동 지점 → 개념의 본질적인 비교 기준 → 실전 접근 전략을 주제별 3~5문장의 자연스러운 단일 문단으로 연결하시오. 반복 라벨 없이 어미도 다양하게 쓰시오. 학습 권장 문단에서 ~시오로 끝나는 직접 지시는 최대 한 문장만 쓰고, 나머지는 이유와 전략을 설명하는 ~이오/~하오/~좋겠소/~유리하오 등으로 연결하시오. 같은 종결 표현을 3문장 이상 반복하지 마시오. 오답 분석도 모든 항목을 ~가리키오/~단서이오로 끝내지 마시오."""


class _Overview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    wrong_summary: str


class _WrongText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    text: str


class _DomainText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnosis: str
    wrong: list[_WrongText]
    focus: str
    guide: str


class ReportDeadlineError(LlmReportError):
    pass


def _compact_wrong(item: dict) -> dict:
    from services.llm_report import _option_explanation
    # Never include unused options or repeat IDs/labels/scores in model output.
    selected = item["options"][item["selected_answer"] - 1]
    correct = item["options"][item["correct_answer"] - 1]
    details = {"correct": item["explanation"]["correct"], "selected": _option_explanation(item, item["selected_answer"]), "correct_option": _option_explanation(item, item["correct_answer"])}
    evidence = list(dict.fromkeys(text.strip() for text in details.values() if text and text.strip()))
    return {"id": item["question_id"], "concept": item["concept"], "question": item["question"], "selected": selected, "correct": correct, "evidence": evidence}


def build_tasks(graded: dict) -> list[tuple[str, dict, type[BaseModel], str]]:
    rows = graded["domain_scores"]
    wrong = [q for q in graded["question_results"] if not q["is_correct"]]
    ranked = sorted((r for r in rows if r["is_vulnerable"]), key=lambda r: r["score"])
    recommended = ranked or ([min(rows, key=lambda r: r["score"])] if rows else [])
    overview = {"score": graded["summary"]["score"], "level": graded["summary"]["level"], "correct": graded["summary"]["correct_count"], "total": graded["summary"]["total_questions"], "domains": [{"label": r["domain_label"], "score": r["score"], "correct": r["correct_count"], "total": r["total_questions"], "missed_concepts": [q["concept"] for q in wrong if q["domain"] == r["domain"]]} for r in rows]}
    tasks = [("overview", overview, _Overview, "총평 summary는 이번 결과와 우선 방향을 2문장으로, wrong_summary는 오답 분포와 공통 구분 기준을 1~2문장으로 설명하시오. 만점이면 없는 약점을 만들지 마시오.")]
    for row in rows:
        domain = row["domain"]
        need_guide = any(r["domain"] == domain for r in recommended)
        payload = {"label": row["domain_label"], "score": row["score"], "correct_count": row["correct_count"], "total": row["total_questions"], "tested_concepts": [q["concept"] for q in graded["question_results"] if q["domain"] == domain], "wrong": [_compact_wrong(q) for q in wrong if q["domain"] == domain], "recommend": need_guide, "maintain": not ranked}
        instructions = "diagnosis는 이번 영역의 정답 수와 확인된 구분 기준을 1~2문장으로 설명하시오. 정답이 0이면 이해가 확인되었다고 쓰지 마시오. 정답인 경우에도 이번 문항 범위의 결과만 말하고 전반적으로 안정적인 실력이라고 확대하지 마시오. wrong은 입력의 모든 오답 id를 정확히 한 번씩 포함하며 text는 실제 선택과 정답의 핵심 차이, 질문 속 단서를 2문장(100~160자 안팎)으로 설명하시오. recommend=true이면 focus는 짧은 학습 주제, guide는 이후 학습 방향과 문제 접근 전략을 3~5문장의 한 문단으로 충분히 제시하시오. maintain=true이면 확인된 개념을 바탕으로 유지·확장 방향을 제시하시오. recommend=false이면 focus와 guide는 빈 문자열이오."
        tasks.append((domain, payload, _DomainText, instructions))
    return tasks


def generate_parallel_report(client, graded: dict, model: str, observer: Callable[[dict], None] | None = None, budget: float = REPORT_BUDGET_SECONDS) -> LlmReportAnalysis:
    started = time.perf_counter()
    deadline = started + budget
    metrics = []
    lock = threading.Lock()
    tasks = build_tasks(graded)

    def call(task):
        name, payload, schema, instruction = task
        queued = time.perf_counter()
        remaining = deadline - queued
        if remaining <= 0 or not _API_SLOTS.acquire(timeout=max(0, remaining)):
            raise ReportDeadlineError("리포트 생성 목표 시간을 초과했소. 잠시 후 다시 요청할 수 있소.")
        try:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise ReportDeadlineError("리포트 생성 목표 시간을 초과했소.")
            api_started = time.perf_counter()
            completion = client.beta.chat.completions.parse(model=model, messages=[{"role": "system", "content": STYLE_PROMPT + "\n" + instruction}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))}], response_format=schema, timeout=remaining)
            if not completion.choices:
                raise LlmReportError("LLM 응답에 분석이 없소.")
            message = completion.choices[0].message
            if getattr(message, "refusal", None) or not isinstance(getattr(message, "parsed", None), schema):
                raise LlmReportError("LLM 분석을 확인할 수 없소.")
            parsed = message.parsed
            if isinstance(parsed, _DomainText):
                ids = [x.id for x in parsed.wrong]
                expected = [x["id"] for x in payload["wrong"]]
                if len(ids) != len(set(ids)) or set(ids) != set(expected):
                    raise LlmReportError("오답 문항 식별자가 채점과 일치하지 않소.")
                if payload["recommend"] and (not parsed.guide.strip() or not parsed.focus.strip()):
                    raise LlmReportError("학습 권장 내용이 누락되었소.")
            usage = getattr(completion, "usage", None)
            metric = {"task": name, "queue_seconds": round(api_started - queued, 4), "api_seconds": round(time.perf_counter() - api_started, 4), "input_tokens": getattr(usage, "prompt_tokens", 0), "output_tokens": getattr(usage, "completion_tokens", 0), "request_id": getattr(completion, "_request_id", None)}
            with lock:
                metrics.append(metric)
            logger.info("report_llm_task %s", json.dumps(metric))
            return parsed
        finally:
            _API_SLOTS.release()

    executor = ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="report")
    futures = {name: executor.submit(call, task) for task in tasks for name in [task[0]]}
    try:
        done, pending = wait(futures.values(), timeout=max(0, deadline - time.perf_counter()), return_when=FIRST_EXCEPTION)
        # Propagate real provider/validation errors before interpreting pending as timeout.
        for future in done:
            if future.exception() is not None:
                raise future.exception()
        if pending:
            raise ReportDeadlineError("리포트 생성 목표 시간을 초과했소. 채점 결과는 보존되어 있소.")
        parsed = {name: future.result() for name, future in futures.items()}
    except LlmReportError:
        raise
    except Exception as exc:
        raise LlmReportError("OpenAI 리포트 생성에 실패했소. 채점 결과는 보존되어 있소.") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    overview = parsed["overview"]
    rows = graded["domain_scores"]
    wrong_items = []
    comments = []
    recommendations = []
    ranked = sorted((r for r in rows if r["is_vulnerable"]), key=lambda r: r["score"])
    recommended = ranked or ([min(rows, key=lambda r: r["score"])] if rows else [])
    for row in rows:
        domain = row["domain"]
        part = parsed[domain]
        comments.append(DomainLevelComment(domain=domain, domain_label=row["domain_label"], score=row["score"], diagnosis=part.diagnosis))
        by_id = {q.id: q.text for q in part.wrong}
        for q in graded["question_results"]:
            if q["domain"] == domain and not q["is_correct"]:
                wrong_items.append(WrongAnswerItem(question_id=q["question_id"], concept=q["concept"], domain=domain, domain_label=row["domain_label"], vulnerability=by_id[q["question_id"]]))
    # Preserve original question order, including interleaved domains.
    order = {q["question_id"]: i for i, q in enumerate(graded["question_results"])}
    wrong_items.sort(key=lambda q: order[q.question_id])
    for priority, row in enumerate(recommended, 1):
        part = parsed[row["domain"]]
        recommendations.append(RecommendationItem(priority=priority, domain=row["domain"], domain_label=row["domain_label"], focus=part.focus, guide=part.guide))
    report = LlmReportAnalysis(level_diagnosis=LevelDiagnosis(overall_level=graded["summary"]["level"], summary=overview.summary, domain_comments=comments), wrong_answer_analysis=WrongAnswerAnalysis(summary=overview.wrong_summary, items=wrong_items), recommendations=recommendations)
    final_metric = {"total_seconds": round(time.perf_counter() - started, 4), "tasks": metrics, "calls": len(tasks)}
    logger.info("report_llm_total %s", json.dumps(final_metric))
    if observer:
        observer(final_metric)
    return report
