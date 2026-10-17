import os
from typing import Annotated

from fastapi import Depends
from services.errors import AuthenticationRequiredError

DUMMY_USER_ID = "test-user-123"


def get_current_user_id() -> str:
    """통합 서버에서는 이 의존성을 공통 인증 함수로 override한다."""
    from database.settings import load_settings
    load_settings()  # .env 로딩
    if os.getenv("DEV_MODE", "false").strip().lower() == "true":
        return DUMMY_USER_ID
    raise AuthenticationRequiredError()


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
