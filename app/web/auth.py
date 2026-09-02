from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import RedirectResponse, Response

from app.config import Settings
from app.db import SessionLocal, get_session
from app.models import User, WebLoginState, WebSession
from app.oauth.google import (
    GOOGLE_AUTHORIZATION_URL,
    GoogleIdentityError,
    exchange_google_identity,
    provision_google_user,
)
from app.security import create_token, hash_token
from app.web.session import (
    WEB_LOGIN_COOKIE,
    WEB_LOGIN_TTL,
    WEB_SESSION_COOKIE,
    WEB_SESSION_TTL,
    csrf_token,
    resolve_web_user,
    secure_cookies,
)

__all__ = [
    "WEB_LOGIN_COOKIE",
    "WEB_LOGIN_TTL",
    "WEB_SESSION_COOKIE",
    "WEB_SESSION_TTL",
    "WebAuth",
    "csrf_token",
    "get_web_user",
    "require_csrf",
    "resolve_web_user",
    "secure_cookies",
    "templates",
]

templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


def _valid_next_path(value: str | None) -> str:
    if value is None or not value.startswith("/app") or value.startswith("//"):
        return "/app"
    return value


async def get_web_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User | RedirectResponse:
    user = await resolve_web_user(session, request)
    if user is not None:
        return user
    if request.method.upper() == "GET":
        query = urlencode({"next": request.url.path})
        return RedirectResponse(f"/web/login?{query}", status_code=status.HTTP_302_FOUND)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Web session required")


async def require_csrf(
    request: Request,
    web_user: User | RedirectResponse = Depends(get_web_user),
) -> User:
    if isinstance(web_user, Response):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Web session required")
    raw_token = request.cookies.get(WEB_SESSION_COOKIE)
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Web session required")
    form = await request.form()
    supplied = str(form.get("csrf_token") or "")
    expected = csrf_token(raw_token, request.app.state.settings)
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token")
    return web_user


class WebAuth:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if settings.app_env.lower() == "production" and not settings.secret_key:
            raise RuntimeError("SECRET_KEY must be configured in production")
        self.settings = settings
        self.transport = transport

    async def login(self, request: Request) -> Response:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            return Response(
                "Google OAuth login is not configured",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        raw_browser_token, browser_hash = create_token()
        state = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            session.add(
                WebLoginState(
                    state=state,
                    browser_hash=browser_hash,
                    next_path=_valid_next_path(request.query_params.get("next")),
                    created_at=now,
                    expires_at=now + WEB_LOGIN_TTL,
                )
            )
            await session.commit()
        query = urlencode(
            {
                "client_id": self.settings.google_client_id,
                "redirect_uri": f"{self.settings.effective_web_base_url}/oauth/google/callback",
                "response_type": "code",
                "scope": "openid email",
                "access_type": "online",
                "prompt": "select_account",
                "state": state,
            }
        )
        response = RedirectResponse(
            f"{GOOGLE_AUTHORIZATION_URL}?{query}",
            status_code=status.HTTP_302_FOUND,
            headers={"Cache-Control": "no-store"},
        )
        response.set_cookie(
            WEB_LOGIN_COOKIE,
            raw_browser_token,
            max_age=int(WEB_LOGIN_TTL.total_seconds()),
            expires=int(WEB_LOGIN_TTL.total_seconds()),
            path="/",
            secure=secure_cookies(self.settings),
            httponly=True,
            samesite="lax",
        )
        return response

    async def callback(self, request: Request) -> Response | None:
        state = request.query_params.get("state")
        if not state:
            return None
        async with SessionLocal() as session:
            login_state = await session.scalar(
                select(WebLoginState).where(WebLoginState.state == state)
            )
        if login_state is None:
            return None
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            return Response(
                "Google OAuth login is not configured",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if login_state.expires_at <= datetime.now(UTC):
            return Response("Invalid or expired web login state", status_code=400)
        browser_token = request.cookies.get(WEB_LOGIN_COOKIE)
        if browser_token is None or not secrets.compare_digest(
            login_state.browser_hash, hash_token(browser_token)
        ):
            return Response("Web login session does not match this browser", status_code=400)
        code = request.query_params.get("code")
        if not code:
            return Response("Google callback requires code and state", status_code=400)
        try:
            email, google_sub = await exchange_google_identity(
                self.settings,
                code,
                self.transport,
                f"{self.settings.effective_web_base_url}/oauth/google/callback",
            )
            user = await provision_google_user(self.settings, email, google_sub)
        except GoogleIdentityError as exc:
            return Response(exc.detail, status_code=exc.status_code)
        raw_session_token, session_hash = create_token()
        async with SessionLocal() as session:
            locked_state = await session.scalar(
                select(WebLoginState).where(WebLoginState.state == state).with_for_update()
            )
            if (
                locked_state is None
                or locked_state.expires_at <= datetime.now(UTC)
                or not secrets.compare_digest(locked_state.browser_hash, hash_token(browser_token))
            ):
                return Response("Invalid or expired web login state", status_code=400)
            next_path = locked_state.next_path or "/app"
            now = datetime.now(UTC)
            session.add(
                WebSession(
                    user_id=user.id,
                    token_hash=session_hash,
                    created_at=now,
                    expires_at=now + WEB_SESSION_TTL,
                    last_seen_at=now,
                )
            )
            await session.delete(locked_state)
            await session.commit()
        response = RedirectResponse(
            next_path,
            status_code=status.HTTP_302_FOUND,
            headers={"Cache-Control": "no-store"},
        )
        response.set_cookie(
            WEB_SESSION_COOKIE,
            raw_session_token,
            max_age=int(WEB_SESSION_TTL.total_seconds()),
            expires=int(WEB_SESSION_TTL.total_seconds()),
            path="/",
            secure=secure_cookies(self.settings),
            httponly=True,
            samesite="lax",
        )
        response.delete_cookie(WEB_LOGIN_COOKIE, path="/")
        return response

    async def logout(self, request: Request, user: User = Depends(require_csrf)) -> Response:
        raw_token = request.cookies.get(WEB_SESSION_COOKIE)
        if raw_token is not None:
            async with SessionLocal() as session:
                record = await session.scalar(
                    select(WebSession).where(WebSession.token_hash == hash_token(raw_token))
                )
                if record is not None:
                    await session.delete(record)
                    await session.commit()
        response = RedirectResponse(
            "/web/login",
            status_code=status.HTTP_302_FOUND,
            headers={"Cache-Control": "no-store"},
        )
        response.delete_cookie(WEB_SESSION_COOKIE, path="/")
        return response

    def router(self) -> APIRouter:
        router = APIRouter()

        @router.get("/")
        async def login_page(request: Request) -> Response:
            return templates.TemplateResponse(request=request, name="login.html", context={})

        @router.get("/web/login")
        async def login(request: Request) -> Response:
            return await self.login(request)

        @router.post("/web/logout")
        async def logout(request: Request, user: User = Depends(require_csrf)) -> Response:
            return await self.logout(request, user)

        return router
