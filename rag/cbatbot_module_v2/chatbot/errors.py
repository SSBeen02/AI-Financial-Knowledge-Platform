"""학습 API의 요청 추적과 공통 오류 응답."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return str(value or uuid.uuid4())


def _code_for_status(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "authentication_required",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        502: "external_service_error",
    }.get(status_code, "internal_server_error" if status_code >= 500 else "request_error")


def _error_response(
    request: Request, *, status_code: int, code: str, message: str
) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


def install_learning_error_handlers(app: FastAPI) -> None:
    """앱 전체에 요청 ID와 `{code,message,request_id}` 오류 형식을 설치한다."""

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("X-Request-ID", "").strip()
        request.state.request_id = incoming[:128] if incoming else str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없습니다."
        return _error_response(
            request,
            status_code=exc.status_code,
            code=_code_for_status(exc.status_code),
            message=message,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="요청 형식이 올바르지 않습니다.",
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # 요청 본문·헤더·예외 문자열을 기록하지 않아 토큰과 비밀번호 노출을 피한다.
        logger.error(
            "Unhandled learning API error request_id=%s path=%s error_type=%s",
            _request_id(request),
            request.url.path,
            type(exc).__name__,
        )
        return _error_response(
            request,
            status_code=500,
            code="internal_server_error",
            message="서버에서 요청을 처리하지 못했습니다.",
        )
