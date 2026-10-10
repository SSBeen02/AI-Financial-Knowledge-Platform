import os
from typing import Annotated
from fastapi import Depends, HTTPException
from database.settings import load_settings

DUMMY_USER_ID = "test-user-123"

def get_current_user_id() -> str:
    """통합 서버는 공통 인증 provider로 override한다."""
    load_settings()
    if os.getenv("DEV_MODE", "false").strip().lower() == "true":
        return DUMMY_USER_ID
    raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

CurrentUserId = Annotated[str, Depends(get_current_user_id)]
