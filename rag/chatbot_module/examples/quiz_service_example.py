"""퀴즈 담당 모듈이 복사해 구현할 ``QuizService`` 뼈대.

저장소는 같은 session_id의 기존 quiz set을 먼저 반환해야 한다. 생성 상태가 명시적으로
failed라면 그 결과를 그대로 반환하고, 호출 자체를 수행하지 못한 예외만 QuizServiceError로
변환한다. 비동기 생성이 나중에 실패하면 ``report_quiz_generation_failed``를 호출한다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastapi import FastAPI

from chatbot.deps import get_quiz_service
from chatbot.quiz import QuizService, QuizServiceError, QuizSetResult


class QuizSetRepository(Protocol):
    def get_by_session_id(self, session_id: str) -> QuizSetResult | None: ...

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


class TeamQuizService(QuizService):
    def __init__(self, repository: QuizSetRepository):
        self._repository = repository

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
        existing = self._repository.get_by_session_id(session_id)
        if existing is not None:
            return existing
        try:
            return self._repository.create_quiz_set(
                user_id=user_id,
                session_id=session_id,
                concept_id=concept_id,
                stage_id=stage_id,
                learning_context=learning_context,
                reference_chunk_ids=reference_chunk_ids,
            )
        except Exception as exc:
            raise QuizServiceError("퀴즈 생성 요청을 수행하지 못했습니다.") from exc


def register_quiz_service_override(
    app: FastAPI,
    provider: Callable[[], QuizService],
) -> None:
    """통합 FastAPI 앱에서 개발용 ``DevQuizService``를 교체한다."""

    app.dependency_overrides[get_quiz_service] = provider
