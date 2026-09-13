from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.security import bearer, resolve_token
from app.web.session import WEB_SESSION_COOKIE, csrf_token, resolve_web_user

CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


async def get_api_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
    csrf_header: str | None = Header(default=None, alias=CSRF_HEADER),
) -> User:
    if credentials is not None:
        if credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing token",
            )
        user = await resolve_token(session, credentials.credentials)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing token",
            )
        request.state.api_auth_method = "bearer"
        return user

    user = await resolve_web_user(session, request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing token",
        )
    request.state.api_auth_method = "cookie"
    if request.method.upper() not in SAFE_METHODS:
        raw_token = request.cookies.get(WEB_SESSION_COOKIE)
        expected = (
            csrf_token(raw_token, request.app.state.settings) if raw_token is not None else ""
        )
        if csrf_header is None or not secrets.compare_digest(
            csrf_header.encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return user
