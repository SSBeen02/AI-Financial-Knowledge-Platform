"""운영 사용자 ID는 공통 인증 의존성이 검증한 값만 사용한다."""
import os
from typing import Annotated
from fastapi import Depends, Header
from database.settings import load_settings
from dependencies import get_current_user_id


def get_authenticated_user_id(
    verified_user_id: Annotated[str, Depends(get_current_user_id)],
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    load_settings()
    # 테스트 헤더는 단독 개발에서만 허용. 서명 미검증 JWT를 읽지 않는다.
    if os.getenv("DEV_MODE", "false").strip().lower() == "true" and x_user_id and x_user_id.strip():
        return x_user_id.strip()
    return verified_user_id

AuthenticatedUserId = Annotated[str, Depends(get_authenticated_user_id)]
