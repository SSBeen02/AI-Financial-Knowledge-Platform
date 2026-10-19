"""Verify bearer tokens with this project's Supabase Auth server."""
import os
from typing import Annotated
from uuid import UUID
from urllib.parse import urlsplit

import httpx
from fastapi import Header, HTTPException, Request


def auth_settings() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip() or os.getenv("SUPABASE_ANON_KEY", "").strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not key:
        raise RuntimeError("SUPABASE_URL(HTTPS origin) 및 SUPABASE_PUBLISHABLE_KEY가 필요합니다.")
    return url, key


async def get_verified_user_id(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip() or " " in token.strip():
        raise HTTPException(401, "로그인이 필요합니다.")
    url, key = auth_settings()
    try:
        response = await request.app.state.auth_client.get(
            url + "/auth/v1/user",
            headers={"apikey": key, "Authorization": "Bearer " + token.strip()},
        )
    except httpx.RequestError:
        raise HTTPException(503, "인증 서버에 연결할 수 없습니다.") from None
    if response.status_code in (401, 403):
        raise HTTPException(401, "로그인이 만료되었거나 유효하지 않습니다.")
    if response.status_code != 200:
        raise HTTPException(503, "인증 서버가 요청을 처리하지 못했습니다.")
    try:
        return str(UUID(response.json()["id"]))
    except (ValueError, KeyError, TypeError):
        raise HTTPException(503, "인증 응답을 확인할 수 없습니다.") from None
