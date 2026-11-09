import copy
import logging
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from database.repository import DiagnosticRepository, get_repository
from schemas.diagnostic import QuestionPublic, ReportResponse, StartDiagnosticResponse, SubmitRequest, SubmitResponse
from services.domains import domain_label, STAGE_DOMAINS
from services.errors import DiagnosticNotFoundError, IdempotencyConflictError, InvalidAnswersError, ReportNotFoundError
from services.grading import grade_attempt
from services.llm_report import generate_llm_report
from services.question_bank import load_questions
from services.report_summary import add_lowest_stage_summary, normalize_report_labels
from services.errors import ReportRetryLimitError
from services.report_safety import validate_report_safety

logger = logging.getLogger("diagnostics")
_service: "DiagnosticService | None" = None
_service_lock = threading.Lock()
# 생성 중 서버가 종료되어도 조회 시 무한 processing 상태를 해소한다.
REPORT_DEADLINE_SECONDS = 30
REPORT_RETRY_LIMIT = 3


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class DiagnosticService:
    def __init__(self, questions: list[dict], repository: DiagnosticRepository) -> None:
        self._questions = copy.deepcopy(questions)
        self._repository = repository

    def start(self, user_id: str) -> StartDiagnosticResponse:
        now = utc_now_iso()
        attempt_id = str(uuid4())
        attempt = self._repository.start_once({
            "id": attempt_id, "user_id": user_id, "status": "pending",
            "started_at": now, "submitted_at": None, "created_at": now, "updated_at": now,
            "questions_snapshot": self._questions, "submission_key": None,
            "answers": None, "summary": None, "domain_scores": None,
            "question_results": None, "vulnerabilities": None, "llm_report": None,
            "report": None, "error": None, "retry_count": 0,
        })
        snapshot = attempt.get("questions_snapshot") or []
        ordered = sorted(snapshot, key=lambda q: STAGE_DOMAINS.index(q["domain"]) if q["domain"] in STAGE_DOMAINS else len(STAGE_DOMAINS))
        return StartDiagnosticResponse(
            id=attempt["id"], user_id=user_id, status=attempt["status"], started_at=attempt["started_at"],
            total_questions=len(snapshot), questions=[_public_question(q) for q in ordered],
            resumed=attempt["id"] != attempt_id,
            report_id=attempt["id"] if attempt["status"] != "pending" else None,
        )

    def submit(self, attempt_id: str, user_id: str, payload: SubmitRequest,
               idempotency_key: str) -> tuple[SubmitResponse, bool]:
        if not idempotency_key.strip():
            raise InvalidAnswersError({"message": "Idempotency-Key는 비어 있을 수 없습니다."})
        attempt = self._repository.get_attempt(attempt_id, user_id)
        if attempt is None:
            raise DiagnosticNotFoundError()
        answers = sorted([item.model_dump() for item in payload.answers], key=lambda item: item["question_id"])
        if attempt["status"] != "pending":
            return self._replay(attempt, answers, idempotency_key), False
        questions = attempt.get("questions_snapshot")
        if not questions:
            raise InvalidAnswersError({"message": "문항 버전이 없는 이전 진단입니다. 새 사전테스트를 시작해 주세요."})
        self._validate_answers(payload, questions)
        graded = grade_attempt(questions, {item.question_id: item.selected_answer for item in payload.answers})
        now = utc_now_iso()
        started = self._repository.update_attempt(attempt_id, user_id, "pending", {
            "status": "processing", "submission_key": idempotency_key,
            "answers": answers, "submitted_at": now, "updated_at": now, **graded,
        })
        if started is None:
            current = self._repository.get_attempt(attempt_id, user_id)
            if current is None:
                raise DiagnosticNotFoundError()
            return self._replay(current, answers, idempotency_key), False
        return self._submit_response(started), True

    def _replay(self, attempt: dict, answers: list[dict], key: str) -> SubmitResponse:
        if attempt.get("submission_key") != key or attempt.get("answers") != answers:
            raise IdempotencyConflictError()
        return self._submit_response(attempt)

    def _submit_response(self, attempt: dict) -> SubmitResponse:
        return SubmitResponse(
            id=attempt["id"], report_id=attempt["id"], user_id=attempt["user_id"],
            status=attempt["status"], submitted_at=attempt["submitted_at"],
            summary=attempt["summary"], domain_scores=attempt["domain_scores"],
            question_results=attempt["question_results"],
        )

    def generate_report(self, attempt_id: str, user_id: str) -> None:
        """라우터가 최초 접수에만 실행. 답안·채점 데이터는 이미 저장되어 있다."""
        started = time.perf_counter()
        generation = None
        try:
            attempt = self._repository.get_attempt(attempt_id, user_id)
            if not attempt or attempt["status"] != "processing":
                return
            generation = attempt.get("retry_count", 0)
            graded = {key: attempt[key] for key in ("summary", "domain_scores", "question_results", "vulnerabilities")}
            began = attempt.get("report_started_at") or attempt["submitted_at"]
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(began.replace("Z", "+00:00"))).total_seconds()
            if elapsed >= REPORT_DEADLINE_SECONDS:
                from services.report_parallel import ReportDeadlineError
                raise ReportDeadlineError("리포트 처리 대기 시간이 처리 기한을 초과했소.")
            llm = generate_llm_report(graded, budget=min(28.0, REPORT_DEADLINE_SECONDS - elapsed))
            validate_report_safety(llm)
            if (datetime.now(timezone.utc) - datetime.fromisoformat(began.replace("Z", "+00:00"))).total_seconds() >= REPORT_DEADLINE_SECONDS:
                from services.report_parallel import ReportDeadlineError
                raise ReportDeadlineError("리포트 생성 처리 기한을 초과했소.")
            # 조회의 기준은 개별 컬럼. report는 이전 데이터 호환용으로 유지한다.
            self._repository.update_attempt(attempt_id, user_id, "processing", {
                "status": "completed", "llm_report": llm.model_dump(),
                "error": None, "updated_at": utc_now_iso(),
            }, generation)
        except Exception as exc:
            from services.report_parallel import ReportDeadlineError
            logger.exception("리포트 작업 실패: diagnostic_id=%s", attempt_id)
            timed_out = isinstance(exc, ReportDeadlineError)
            self._fail(attempt_id, user_id, "REPORT_GENERATION_TIMEOUT" if timed_out else "REPORT_GENERATION_FAILED", "리포트 생성 처리 기한을 초과했소. 채점 결과는 보존되어 있소." if timed_out else "리포트를 생성하지 못했소. 채점 결과는 보존되어 있소.", generation)
        finally:
            logger.info("report_service_total diagnostic_id=%s seconds=%.4f", attempt_id, time.perf_counter() - started)

    def _fail(self, attempt_id: str, user_id: str, code: str, message: str, generation: int | None = None) -> None:
        try:
            self._repository.update_attempt(attempt_id, user_id, "processing", {
                "status": "failed", "llm_report": None,
                "error": {"code": code, "message": message}, "updated_at": utc_now_iso(),
            }, generation)
        except Exception:
            logger.exception("리포트 실패 상태 저장 실패: diagnostic_id=%s", attempt_id)

    def prepare_report_retry(self, report_id: str, user_id: str) -> bool:
        """실패한 리포트만 processing으로 되돌립니다. 이미 생성 중이거나 완료면 False입니다."""
        attempt = self._repository.get_attempt(report_id, user_id)
        if attempt is None:
            raise ReportNotFoundError()
        if attempt["status"] != "failed":
            if attempt["status"] == "pending" or not attempt.get("summary"):
                raise InvalidAnswersError({"message": "답안을 제출한 뒤에 리포트를 다시 생성할 수 있습니다."})
            return False
        if not attempt.get("summary"):
            raise InvalidAnswersError({"message": "채점 결과가 없어 리포트를 다시 생성할 수 없습니다."})
        retry_count = attempt.get("retry_count", 0)
        if retry_count >= REPORT_RETRY_LIMIT:
            raise ReportRetryLimitError()
        now = utc_now_iso()
        updated = self._repository.update_attempt(report_id, user_id, "failed", {
            "status": "processing",
            "error": None,
            "llm_report": None,
            "report_started_at": now,
            "updated_at": now,
            "retry_count": retry_count + 1,
        }, retry_count)
        return updated is not None

    def get_report(self, report_id: str, user_id: str) -> ReportResponse:
        attempt = self._repository.get_attempt(report_id, user_id)
        if attempt is None:
            raise ReportNotFoundError()
        if attempt["status"] == "processing":
            started = datetime.fromisoformat((attempt.get("report_started_at") or attempt["submitted_at"]).replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - started).total_seconds() > REPORT_DEADLINE_SECONDS:
                self._fail(report_id, user_id, "REPORT_GENERATION_TIMEOUT", "생성 시간이 초과되었습니다. 채점 결과는 저장되어 있습니다.", attempt.get("retry_count", 0))
                attempt = self._repository.get_attempt(report_id, user_id) or attempt
        # 이전 완료 데이터의 report 컬럼을 읽되 새 데이터는 개별 컬럼을 우선한다.
        result = dict(attempt.get("report") or {})
        result.update({
            "id": attempt["id"], "diagnostic_id": attempt["id"], "user_id": attempt["user_id"],
            "status": attempt["status"], "created_at": attempt.get("submitted_at") or attempt["created_at"],
            "retry_count": attempt.get("retry_count", 0), "retry_limit": REPORT_RETRY_LIMIT,
        })
        for key in ("summary", "domain_scores", "question_results", "vulnerabilities", "llm_report", "error"):
            if attempt.get(key) is not None:
                result[key] = copy.deepcopy(attempt[key])
        if attempt["status"] != "completed":
            result.pop("llm_report", None)
        if attempt["status"] != "failed":
            result.pop("error", None)
        if isinstance(result.get("llm_report"), dict):
            result["llm_report"].pop("unpassed_concepts", None)
        response = ReportResponse.model_validate(normalize_report_labels(result))
        if response.llm_report is not None:
            try:
                validate_report_safety(response.llm_report)
            except Exception:
                # 과거에 저장된 위험 문구도 재조회 시 노출하지 않는다.
                response.llm_report = None
                logger.warning("unsafe_saved_report_hidden diagnostic_id=%s", report_id)
        if response.llm_report is not None and response.domain_scores:
            response.llm_report = add_lowest_stage_summary(
                response.llm_report, [row.model_dump() for row in response.domain_scores]
            )
        return response

    def _validate_answers(self, payload: SubmitRequest, questions: list[dict]) -> None:
        question_ids = [item.question_id for item in payload.answers]
        counts = Counter(question_ids)
        duplicates = [question_id for question_id, count in counts.items() if count > 1]
        by_id = {q["id"]: q for q in questions}
        known_ids = [question["id"] for question in questions]
        known = set(known_ids)
        unknown: list[str] = []
        seen_unknown: set[str] = set()
        out_of_range: list[str] = []
        for item in payload.answers:
            if item.question_id not in known:
                if item.question_id not in seen_unknown:
                    unknown.append(item.question_id)
                    seen_unknown.add(item.question_id)
                continue
            option_count = len(by_id[item.question_id]["options"])
            if item.selected_answer > option_count:
                out_of_range.append(item.question_id)

        submitted = set(question_ids)
        missing = [question_id for question_id in known_ids if question_id not in submitted]
        if not (missing or unknown or duplicates or out_of_range):
            return

        detail: dict = {"message": "모든 문항에 대해 답안을 한 번씩, 보기 번호 안에서 제출해 주세요."}
        if missing:
            detail["missing_question_ids"] = missing
        if unknown:
            detail["unknown_question_ids"] = unknown
        if duplicates:
            detail["duplicate_question_ids"] = duplicates
        if out_of_range:
            detail["out_of_range_question_ids"] = out_of_range
        raise InvalidAnswersError(detail)


def _public_question(question: dict) -> QuestionPublic:
    return QuestionPublic(
        id=question["id"],
        domain=question["domain"],
        domain_label=domain_label(question["domain"]),
        category=question["category"],
        difficulty=question["difficulty"],
        question=question["question"],
        options=list(question["options"]),
    )


def get_diagnostic_service() -> DiagnosticService:
    global _service
    if _service is not None:
        return _service
    with _service_lock:
        if _service is None:
            _service = DiagnosticService(load_questions(), get_repository())
        return _service
