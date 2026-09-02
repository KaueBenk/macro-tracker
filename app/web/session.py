from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import User, WebSession
from app.security import hash_token

WEB_LOGIN_COOKIE = "mt_web_login"
WEB_SESSION_COOKIE = "mt_web_session"
WEB_LOGIN_TTL = timedelta(minutes=10)
WEB_SESSION_TTL = timedelta(days=30)


def secure_cookies(settings: Settings) -> bool:
    return settings.effective_web_base_url.lower().startswith("https://")


def csrf_token(raw_session_token: str, settings: Settings) -> str:
    if settings.app_env.lower() == "production" and not settings.secret_key:
        raise RuntimeError("SECRET_KEY must be configured in production")
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        raw_session_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def resolve_web_user(session: AsyncSession, request: Request) -> User | None:
    raw_token = request.cookies.get(WEB_SESSION_COOKIE)
    if not raw_token:
        return None
    token_hash = hash_token(raw_token)
    record = await session.scalar(select(WebSession).where(WebSession.token_hash == token_hash))
    if record is None or not secrets.compare_digest(record.token_hash, token_hash):
        return None
    if record.expires_at <= datetime.now(UTC):
        await session.delete(record)
        await session.commit()
        return None
    user = await session.get(User, record.user_id)
    if user is None:
        return None
    record.last_seen_at = datetime.now(UTC)
    try:
        await session.commit()
    except Exception:
        await session.rollback()
    return user
