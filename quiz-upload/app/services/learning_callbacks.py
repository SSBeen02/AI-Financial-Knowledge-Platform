"""학습 관리 모듈로 넘기는 호출.

학습 모듈이 같은 실패나 같은 submission_id를 여러 번 받아도 한 번만 반영합니다.
개념 통과 여부는 여기서 저장하지 않습니다.
"""

from __future__ import annotations

import logging
import asyncio
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("quiz")

_store_provider: Callable[[], Any] | None = None
_status_provider: Callable[[], Any] | None = None


def configure_learning_callbacks(*, store_provider, status_provider) -> None:
    """통합 서버 시작 시 실제 학습 관리 provider를 등록한다."""
    global _store_provider, _status_provider
    _store_provider = store_provider
    _status_provider = status_provider


async def report_quiz_generation_failed(session_id: str, *, user_id: str) -> None:
    """퀴즈 생성이 실패했음을 학습 세션 단위로 알립니다."""
    if _store_provider is None:
        logger.warning("학습 관리 미연결: 생성 실패 알림 session_id=%s", session_id)
        return
    from chatbot.service import report_quiz_generation_failed as notify

    await asyncio.to_thread(
        lambda: notify(store=_store_provider(), user_id=user_id, session_id=session_id)
    )


async def report_quiz_result(
    *,
    user_id: str,
    submission_id: str,
    session_id: str,
    concept_id: str,
    stage_id: str | None,
    correct_count: int,
    passed: bool,
) -> None:
    """채점 결과를 그 퀴즈의 session_id로 알립니다."""
    if _store_provider is None or _status_provider is None:
        logger.warning("학습 관리 미연결: 결과 보고 submission_id=%s", submission_id)
        return
    if not stage_id:
        raise ValueError("학습 결과 보고에는 stage_id가 필요합니다.")
    from chatbot.service import report_quiz_result as notify

    await asyncio.to_thread(
        lambda: notify(
            store=_store_provider(), status_service=_status_provider(),
            user_id=user_id, submission_id=submission_id, session_id=session_id,
            concept_id=concept_id, stage_id=stage_id,
            correct_count=correct_count, passed=passed,
        )
    )
