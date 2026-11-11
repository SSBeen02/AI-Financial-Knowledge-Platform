"""Request-scoped timing markers for the learning SSE path."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Iterator


logger = logging.getLogger("uvicorn.error")


class RequestTiming:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.started_at = perf_counter()

    def mark(self, phase: str) -> None:
        logger.info(
            "learning_stream_timing request_id=%r phase=%s elapsed_ms=%.1f",
            self.request_id,
            phase,
            (perf_counter() - self.started_at) * 1000,
        )


_current: ContextVar[RequestTiming | None] = ContextVar("learning_timing", default=None)


def current_timing() -> RequestTiming | None:
    return _current.get()


@contextmanager
def timing_scope(timing: RequestTiming | None) -> Iterator[None]:
    token = _current.set(timing)
    try:
        yield
    finally:
        _current.reset(token)
