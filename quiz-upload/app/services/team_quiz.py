"""유빈님 동기 QuizService 계약과 서현님 비동기 DB 서비스를 연결한다."""

import asyncio
from typing import Any

from app.db import session_scope
from app.services.quiz_service import QuizService


class TeamQuizService:
    def __init__(self, loop: asyncio.AbstractEventLoop, service: QuizService | None = None):
        self.loop = loop
        self.service = service if service is not None else QuizService()

    def create_quiz_set(
        self, *, user_id: str, session_id: str, concept_id: str, stage_id: str,
        learning_context: dict[str, Any], reference_chunk_ids: list[str],
    ):
        from chatbot.quiz import QuizServiceError

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise QuizServiceError("동기 QuizService는 작업 스레드에서 호출해야 합니다.")
        if not self.loop.is_running():
            raise QuizServiceError("퀴즈 서버 이벤트 루프가 실행 중이 아닙니다.")
        coroutine = self._create(
            user_id=user_id, session_id=session_id, concept_id=concept_id,
            stage_id=stage_id, learning_context=learning_context,
            reference_chunk_ids=reference_chunk_ids,
        )
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        except Exception as exc:
            coroutine.close()
            raise QuizServiceError("퀴즈 생성 요청을 수행하지 못했습니다.") from exc
        try:
            return future.result()
        except Exception as exc:
            raise QuizServiceError("퀴즈 생성 요청을 수행하지 못했습니다.") from exc

    async def _create(self, **kwargs):
        from chatbot.quiz import QuizSetResult

        async with session_scope() as session:
            result = await self.service.create_quiz_set(session, **kwargs)
        return QuizSetResult(quiz_set_id=result.id, status=result.status)


def register_quiz_integration(app, *, store_provider=None, status_provider=None):
    """통합 앱 async lifespan 안에서 호출. 챗봇 초기화 후 등록한다."""
    from chatbot.deps import get_chat_store, get_concept_status_service, get_quiz_service
    from app.services.learning_callbacks import configure_learning_callbacks

    adapter = TeamQuizService(asyncio.get_running_loop())
    app.dependency_overrides[get_quiz_service] = lambda: adapter
    configure_learning_callbacks(
        store_provider=store_provider or app.dependency_overrides.get(get_chat_store, get_chat_store),
        status_provider=status_provider or app.dependency_overrides.get(get_concept_status_service, get_concept_status_service),
    )
    return adapter
