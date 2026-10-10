"""토큰 또는 헤더로 사용자를 식별합니다. 요청 본문의 user_id는 사용하지 않습니다."""

from __future__ import annotations

import base64
import json
from typing import Annotated

from fastapi import Depends, Header

from dependencies import get_current_user_id


def subject_from_authorization(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    parts = token.strip().split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + padding))
    except (ValueError, json.JSONDecodeError):
        return None
    subject = data.get("sub")
    if isinstance(subject, str) and subject.strip():
        return subject.strip()
    return None


def get_authenticated_user_id(
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """Authorization Bearer JWT의 sub, 없으면 X-User-Id, 없으면 공통 인증 모듈의 임시 사용자."""
    subject = subject_from_authorization(authorization)
    if subject:
        return subject
    if x_user_id and x_user_id.strip():
        return x_user_id.strip()
    return get_current_user_id()


AuthenticatedUserId = Annotated[str, Depends(get_authenticated_user_id)]
