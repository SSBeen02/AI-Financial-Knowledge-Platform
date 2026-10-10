"""퀴즈 API 오류. 응답 본문은 code, message, request_id 세 필드입니다."""

from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class QuizAPIError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


class QuizGenerationError(Exception):
    """생성에 실패해도 개념 통과 처리로 넘어가지 않습니다."""

    code = "QUIZ_GENERATION_FAILED"
    concept_status = "in_progress"

    def __init__(self, *, quiz_set_id: str, concept_id: str, message: str):
        self.quiz_set_id = quiz_set_id
        self.concept_id = concept_id
        self.status = "failed"
        self.message = message
        super().__init__(message)


def quiz_not_found() -> QuizAPIError:
    return QuizAPIError(404, "QUIZ_SET_NOT_FOUND", "퀴즈를 찾을 수 없습니다.")


def quiz_not_ready() -> QuizAPIError:
    return QuizAPIError(409, "QUIZ_NOT_READY", "퀴즈 생성이 끝나지 않아 제출할 수 없습니다.")


def invalid_submission(message: str) -> QuizAPIError:
    return QuizAPIError(422, "INVALID_SUBMISSION", message)


def idempotency_conflict() -> QuizAPIError:
    return QuizAPIError(409, "IDEMPOTENCY_CONFLICT", "같은 idempotency_key가 다른 퀴즈에 이미 사용되었습니다.")


def _request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return str(uuid.uuid4())


def error_body(request: Request, code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message, "request_id": _request_id(request)}


async def request_id_middleware(request: Request, call_next):
    incoming = request.headers.get("x-request-id", "").strip()
    request.state.request_id = incoming or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


async def quiz_api_error_handler(request: Request, exc: QuizAPIError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(request, exc.code, exc.message),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError):
    path = request.url.path
    if not (path.startswith("/api/v1/") or path.startswith("/diagnostics") or path.startswith("/reports")):
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


def register_quiz_exception_handlers(app: FastAPI) -> None:
    app.middleware("http")(request_id_middleware)
    app.add_exception_handler(QuizAPIError, quiz_api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
