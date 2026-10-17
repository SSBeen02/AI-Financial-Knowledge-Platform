import uuid

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from services.errors import (
    AuthenticationRequiredError,
    IdempotencyConflictError,
    DiagnosticAlreadySubmittedError,
    DiagnosticError,
    DiagnosticNotFoundError,
    DiagnosticStorageError,
    InvalidAnswersError,
    LlmReportError,
    ReportNotFoundError,
)


def is_pretest_path(path: str) -> bool:
    return path.startswith("/diagnostics") or path.startswith("/reports")


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return str(uuid.uuid4())


def error_body(request: Request, code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "request_id": _request_id(request)}


def _invalid_answer_message(exc: InvalidAnswersError) -> str:
    detail = exc.detail
    parts = [detail.get("message") or "답안이 올바르지 않습니다."]
    labels = (
        ("missing_question_ids", "빠진 문항"),
        ("unknown_question_ids", "없는 문항"),
        ("duplicate_question_ids", "중복된 문항"),
        ("out_of_range_question_ids", "보기 범위를 벗어난 문항"),
    )
    for key, label in labels:
        values = detail.get(key) or []
        if values:
            parts.append(f"{label}: {', '.join(values)}")
    return " ".join(parts)


def describe_diagnostic_error(exc: DiagnosticError) -> tuple[int, str, str]:
    if isinstance(exc, AuthenticationRequiredError):
        return 401, "AUTHENTICATION_REQUIRED", "로그인 후 사전테스트를 이용해 주세요."
    if isinstance(exc, IdempotencyConflictError):
        return 409, "IDEMPOTENCY_CONFLICT", "이미 다른 키 또는 답안으로 제출한 진단입니다."
    if isinstance(exc, InvalidAnswersError):
        return 422, "INVALID_ANSWERS", _invalid_answer_message(exc)
    if isinstance(exc, DiagnosticNotFoundError):
        return 404, "DIAGNOSTIC_NOT_FOUND", "진단 정보를 찾을 수 없습니다."
    if isinstance(exc, DiagnosticAlreadySubmittedError):
        return (
            409,
            "REPORT_ALREADY_REQUESTED",
            "이미 리포트 생성을 요청했습니다. GET /reports/{id}로 상태를 확인해 주세요.",
        )
    if isinstance(exc, ReportNotFoundError):
        return 404, "REPORT_NOT_FOUND", exc.message
    if isinstance(exc, LlmReportError):
        return 502, "REPORT_GENERATION_FAILED", exc.message
    if isinstance(exc, DiagnosticStorageError):
        return 503, "DIAGNOSTIC_STORAGE_FAILED", exc.message
    return 500, "DIAGNOSTIC_FAILED", "사전테스트를 처리하지 못했습니다."


async def request_id_middleware(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "").strip()
    request.state.request_id = incoming or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


async def diagnostic_error_handler(request: Request, exc: DiagnosticError) -> JSONResponse:
    status_code, code, message = describe_diagnostic_error(exc)
    return JSONResponse(status_code=status_code, content=error_body(request, code, message))


async def pretest_validation_handler(request: Request, exc: RequestValidationError):
    if not is_pretest_path(request.url.path):
        return await request_validation_exception_handler(request, exc)
    fields = []
    for item in exc.errors():
        loc = [str(part) for part in item.get("loc", []) if part != "body"]
        if loc:
            fields.append(".".join(loc))
    message = "요청 값이 올바르지 않습니다."
    if fields:
        message = f"{message}: {', '.join(fields)}"
    return JSONResponse(status_code=422, content=error_body(request, "VALIDATION_ERROR", message))


def register_pretest_exception_handlers(app: FastAPI, *, include_validation: bool = True) -> None:
    app.middleware("http")(request_id_middleware)
    app.add_exception_handler(DiagnosticError, diagnostic_error_handler)
    if include_validation:
        app.add_exception_handler(RequestValidationError, pretest_validation_handler)
