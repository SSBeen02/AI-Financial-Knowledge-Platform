"""퀴즈 모듈 연동 계약과 로컬 개발용 구현."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal

from chatbot.config import Settings

QuizGenerationStatus = Literal["pending", "processing", "completed", "failed"]


class QuizServiceError(Exception):
    """퀴즈 생성 요청 자체를 수행하지 못했을 때."""


@dataclass(frozen=True)
class QuizSetResult:
    quiz_set_id: str
    status: QuizGenerationStatus


class QuizService(ABC):
    """퀴즈 담당 모듈이 구현하는 최소 인터페이스."""

    @abstractmethod
    def create_quiz_set(
        self,
        *,
        user_id: str,
        session_id: str,
        concept_id: str,
        stage_id: str,
        learning_context: dict[str, Any],
        reference_chunk_ids: list[str],
    ) -> QuizSetResult: ...


class DevQuizService(QuizService):
    """외부 호출 없이 session_id별 멱등 결과를 반환하는 개발 구현."""

    def __init__(self, settings: Settings):
        self._simulate_failure = settings.dev_simulate_quiz_generation_failure
        self._results: dict[str, QuizSetResult] = {}
        self._lock = Lock()

    def create_quiz_set(
        self,
        *,
        user_id: str,
        session_id: str,
        concept_id: str,
        stage_id: str,
        learning_context: dict[str, Any],
        reference_chunk_ids: list[str],
    ) -> QuizSetResult:
        del user_id, concept_id, stage_id, learning_context, reference_chunk_ids
        with self._lock:
            existing = self._results.get(session_id)
            if existing is not None:
                return existing
            result = QuizSetResult(
                quiz_set_id=str(uuid.uuid4()),
                status="failed" if self._simulate_failure else "pending",
            )
            self._results[session_id] = result
            return result
