from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.models import User, WebLoginState, WebSession
from app.oauth.google import (
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    GoogleIdentityProvider,
    create_google_callback_route,
)
from app.oauth.provider import DbOAuthProvider
from app.security import hash_token
from app.web.auth import (
    WEB_LOGIN_COOKIE,
    WEB_SESSION_COOKIE,
    WebAuth,
    csrf_token,
)
from app.web.pages import router as web_pages_router


def _settings(
    *,
    google_client_id: str = "google-client-id",
    google_client_secret: str = "google-client-secret",
) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/macro_tracker_taco",
        app_env="development",
        public_base_url="http://localhost:8000",
        secret_key="test-secret",
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
        allowed_emails="web@example.com",
    )


def _app(
    settings: Settings,
    handler: httpx.AsyncBaseTransport,
) -> FastAPI:
    application = FastAPI()
    application.state.settings = settings
    provider = DbOAuthProvider()
    google = GoogleIdentityProvider(provider, settings, handler)
    web = WebAuth(settings, handler)
    application.include_router(web_pages_router)
    application.include_router(web.router())
    application.router.routes.append(
        create_google_callback_route(
            google,
            provider,
            settings,
            web_callback=web.callback,
        )
    )
    return application


def _transport() -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "access-token"})
        assert request.url == httpx.URL(GOOGLE_USERINFO_URL)
        return httpx.Response(
            200,
            json={"sub": "web-sub", "email": "web@example.com", "email_verified": True},
        )

    return httpx.MockTransport(handler)


async def _client(
    application: FastAPI,
) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=application),
        base_url="http://localhost:8000",
    )


@pytest.mark.asyncio
async def test_web_login_and_callback_create_session() -> None:
    settings = _settings()
    application = _app(settings, _transport())
    async with await _client(application) as client:
        login = await client.get(
            "/web/login",
            params={"next": "/app/summary"},
            follow_redirects=False,
        )
        assert login.status_code == 302
        assert WEB_LOGIN_COOKIE in login.cookies
        google = urlparse(login.headers["location"])
        params = parse_qs(google.query)
        assert params["redirect_uri"] == ["http://localhost:8000/oauth/google/callback"]
        assert params["scope"] == ["openid email"]
        assert params["prompt"] == ["select_account"]
        state = params["state"][0]
        callback = await client.get(
            "/oauth/google/callback",
            params={"code": "google-code", "state": state},
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert callback.headers["location"] == "/app/summary"
        assert WEB_SESSION_COOKIE in callback.cookies
        assert f"{WEB_LOGIN_COOKIE}=" in callback.headers["set-cookie"]

    async with SessionLocal() as session:
        assert (
            await session.scalar(select(WebLoginState).where(WebLoginState.state == state)) is None
        )
        web_session = await session.scalar(select(WebSession))
        assert web_session is not None
        assert web_session.token_hash not in (callback.cookies.get(WEB_SESSION_COOKIE) or "")


@pytest.mark.asyncio
@pytest.mark.parametrize("next_value", ["https://evil.com", "//evil.com", "/etc"])
async def test_web_login_rejects_external_next(next_value: str) -> None:
    settings = _settings()
    application = _app(settings, _transport())
    async with await _client(application) as client:
        response = await client.get(
            "/web/login", params={"next": next_value}, follow_redirects=False
        )
        state = parse_qs(urlparse(response.headers["location"]).query)["state"][0]
        callback = await client.get(
            "/oauth/google/callback",
            params={"code": "code", "state": state},
            follow_redirects=False,
        )
        assert callback.headers["location"] == "/app"


@pytest.mark.asyncio
async def test_web_callback_rejects_other_browser_and_expired_state() -> None:
    settings = _settings()
    application = _app(settings, _transport())
    async with await _client(application) as first:
        login = await first.get("/web/login", follow_redirects=False)
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
        async with await _client(application) as other:
            wrong = await other.get(
                "/oauth/google/callback",
                params={"code": "code", "state": state},
                follow_redirects=False,
            )
            assert wrong.status_code == 400
        async with SessionLocal() as session:
            record = await session.scalar(select(WebLoginState).where(WebLoginState.state == state))
            assert record is not None
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        expired = await first.get(
            "/oauth/google/callback",
            params={"code": "code", "state": state},
            follow_redirects=False,
        )
        assert expired.status_code == 400


@pytest.mark.asyncio
async def test_app_requires_session_and_logout_requires_csrf() -> None:
    settings = _settings()
    application = _app(settings, _transport())
    user = User(email="web@example.com", timezone="America/Sao_Paulo")
    raw_session = "session-token"
    async with SessionLocal() as session:
        session.add(user)
        await session.flush()
        session.add(
            WebSession(
                user_id=user.id,
                token_hash=hash_token(raw_session),
                created_at=datetime.now(UTC),
                expires_at=datetime.now(UTC) + timedelta(days=1),
                last_seen_at=datetime.now(UTC),
            )
        )
        await session.commit()
    async with await _client(application) as client:
        missing = await client.get("/app", follow_redirects=False)
        assert missing.status_code == 302
        assert missing.headers["location"].startswith("/web/login?next=%2Fapp")
        client.cookies.set(WEB_SESSION_COOKIE, raw_session)
        page = await client.get("/app")
        assert page.status_code == 200
        assert "Hoje" in page.text
        no_csrf = await client.post("/web/logout", follow_redirects=False)
        assert no_csrf.status_code == 403
        csrf = csrf_token(raw_session, settings)
        logged_out = await client.post(
            "/web/logout",
            data={"csrf_token": csrf},
            follow_redirects=False,
        )
        assert logged_out.status_code == 302
        assert logged_out.headers["location"] == "/web/login"
    async with SessionLocal() as session:
        assert await session.scalar(select(WebSession)) is None


@pytest.mark.asyncio
async def test_web_login_requires_google_configuration() -> None:
    settings = _settings(google_client_id="", google_client_secret="")
    application = _app(settings, _transport())
    async with await _client(application) as client:
        response = await client.get("/web/login")
    assert response.status_code == 503
    assert "Google OAuth login is not configured" in response.text
