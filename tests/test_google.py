import base64
import hashlib
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.routes import create_auth_routes
from sqlalchemy import select
from starlette.applications import Starlette

from app.config import Settings, get_auth_settings
from app.db import SessionLocal
from app.models import OAuthAuthCode, OAuthPendingAuth, User
from app.oauth.google import (
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    GoogleIdentityProvider,
    create_google_callback_route,
)
from app.oauth.identity import create_consent_routes, create_login_route
from app.oauth.provider import DbOAuthProvider
from tests.conftest import create_identity


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _settings(
    *,
    allowed_emails: str = "new@example.com",
    google_client_id: str = "google-client-id",
    google_client_secret: str = "google-client-secret",
    oauth_require_consent: bool = True,
) -> Settings:
    return Settings(
        database_url="postgresql+asyncpg://postgres:postgres@localhost:5432/macro_tracker_test",
        app_env="production",
        public_base_url="http://localhost:8000",
        google_client_id=google_client_id,
        google_client_secret=google_client_secret,
        allowed_emails=allowed_emails,
        oauth_require_consent=oauth_require_consent,
    )


def _google_app(
    settings: Settings,
    handler: Callable[[httpx.Request], Coroutine[None, None, httpx.Response]],
) -> Starlette:
    provider = DbOAuthProvider()
    google = GoogleIdentityProvider(provider, settings, httpx.MockTransport(handler))
    auth = get_auth_settings()
    routes = create_auth_routes(
        provider=provider,
        issuer_url=auth.issuer_url,
        client_registration_options=auth.client_registration_options,
        revocation_options=auth.revocation_options,
    )
    routes.append(create_login_route(provider, google, settings))
    routes.append(create_google_callback_route(google, provider, settings))
    routes.extend(create_consent_routes(provider))
    return Starlette(routes=routes)


async def _register(client: AsyncClient, client_name: str = "Spark") -> str:
    response = await client.post(
        "/register",
        json={
            "client_name": client_name,
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "scope": "mcp",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body, dict)
    client_id = body.get("client_id")
    assert isinstance(client_id, str)
    return client_id


async def _start_google(client: AsyncClient, client_id: str) -> tuple[str, str]:
    verifier = "google-flow-verifier"
    authorization = await client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "scope": "mcp",
            "state": "oauth-state",
        },
        follow_redirects=False,
    )
    assert authorization.status_code == 302
    login = await client.get(authorization.headers["location"], follow_redirects=False)
    assert login.status_code == 302
    set_cookie = login.headers["set-cookie"]
    cookie_name, cookie_value = set_cookie.split(";", 1)[0].split("=", 1)
    assert cookie_name == "mt_oauth_browser"
    assert "HttpOnly" in set_cookie
    assert "Max-Age=600" in set_cookie
    assert "Path=/" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Secure" in set_cookie
    client.cookies.set(cookie_name, cookie_value)
    google_url = urlparse(login.headers["location"])
    return verifier, google_url.query


@pytest.mark.asyncio
async def test_google_flow_and_consent() -> None:
    requests: list[httpx.Request] = []

    async def google_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            form = parse_qs(request.content.decode())
            assert form["code"] == ["google-code"]
            assert form["client_id"] == ["google-client-id"]
            assert form["client_secret"] == ["google-client-secret"]
            assert form["redirect_uri"] == ["http://localhost:8000/oauth/google/callback"]
            assert form["grant_type"] == ["authorization_code"]
            return httpx.Response(200, json={"access_token": "google-access-token"})
        assert request.url == httpx.URL(GOOGLE_USERINFO_URL)
        assert request.headers["authorization"] == "Bearer google-access-token"
        return httpx.Response(
            200,
            json={"sub": "google-sub", "email": "new@example.com", "email_verified": True},
        )

    settings = _settings()
    application = _google_app(settings, google_handler)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        client_id = await _register(client)
        verifier, google_query = await _start_google(client, client_id)
        google_params = parse_qs(google_query)
        assert google_params["client_id"] == ["google-client-id"]
        assert google_params["redirect_uri"] == ["http://localhost:8000/oauth/google/callback"]
        assert google_params["response_type"] == ["code"]
        assert google_params["scope"] == ["openid email"]
        assert google_params["access_type"] == ["online"]
        assert google_params["prompt"] == ["select_account"]
        login_state = google_params["state"][0]

        callback = await client.get(
            "/oauth/google/callback",
            params={"code": "google-code", "state": login_state},
            follow_redirects=False,
        )
        assert callback.status_code == 302
        consent_url = urlparse(callback.headers["location"])
        consent = await client.get(consent_url.path + "?" + consent_url.query)
        assert consent.status_code == 200
        assert "Spark" in consent.text
        assert "Autorizar" in consent.text
        assert "Cancelar" in consent.text

        authorized = await client.post(
            "/oauth/consent",
            data={
                "pending": parse_qs(consent_url.query)["pending"][0],
                "action": "authorize",
            },
            follow_redirects=False,
        )
        assert authorized.status_code == 302
        redirect = urlparse(authorized.headers["location"])
        assert parse_qs(redirect.query)["state"] == ["oauth-state"]
        code = parse_qs(redirect.query)["code"][0]
        token = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": verifier,
            },
        )
        assert token.status_code == 200
        assert len(requests) == 2
        assert 'mt_oauth_browser="";' in authorized.headers["set-cookie"]
        assert "Max-Age=0" in authorized.headers["set-cookie"]

    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == "new@example.com"))
        assert user is not None
        assert user.google_sub == "google-sub"


@pytest.mark.asyncio
async def test_google_invalid_state_and_unverified_email() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={"sub": "unverified-sub", "email": "new@example.com", "email_verified": False},
        )

    settings = _settings()
    application = _google_app(settings, handler)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        client_id = await _register(client)
        _, query = await _start_google(client, client_id)
        state = parse_qs(query)["state"][0]
        invalid = await client.get(
            "/oauth/google/callback",
            params={"code": "google-code", "state": state + "-wrong"},
        )
        assert invalid.status_code == 400
        rejected = await client.get(
            "/oauth/google/callback",
            params={"code": "google-code", "state": state},
        )
        assert rejected.status_code == 403
        assert "verified" in rejected.json()["detail"]


@pytest.mark.asyncio
async def test_google_existing_email_and_subject_are_idempotent() -> None:
    existing, _ = await create_identity("existing@example.com")

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={"sub": "existing-sub", "email": "existing@example.com", "email_verified": True},
        )

    settings = _settings(allowed_emails="")
    application = _google_app(settings, handler)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        client_id = await _register(client)
        _, query = await _start_google(client, client_id)
        state = parse_qs(query)["state"][0]
        callback = await client.get(
            "/oauth/google/callback", params={"code": "code", "state": state}
        )
        assert callback.status_code == 302
        pending_id = UUID(parse_qs(urlparse(callback.headers["location"]).query)["pending"][0])
        async with SessionLocal() as session:
            linked = await session.get(User, existing.id)
            assert linked is not None
            assert linked.google_sub == "existing-sub"
            pending = await session.get(OAuthPendingAuth, pending_id)
            assert pending is not None
            assert pending.user_id == existing.id


@pytest.mark.asyncio
async def test_google_disallows_new_email_without_allowlist() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={"sub": "blocked-sub", "email": "blocked@example.com", "email_verified": True},
        )

    settings = _settings(allowed_emails="")
    application = _google_app(settings, handler)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        client_id = await _register(client)
        _, query = await _start_google(client, client_id)
        response = await client.get(
            "/oauth/google/callback",
            params={"code": "code", "state": parse_qs(query)["state"][0]},
        )
        assert response.status_code == 403
        assert "allowlist" in response.json()["detail"]


@pytest.mark.asyncio
async def test_google_consent_can_be_cancelled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={"sub": "cancel-sub", "email": "new@example.com", "email_verified": True},
        )

    settings = _settings()
    application = _google_app(settings, handler)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        client_id = await _register(client)
        _, query = await _start_google(client, client_id)
        callback = await client.get(
            "/oauth/google/callback",
            params={"code": "code", "state": parse_qs(query)["state"][0]},
            follow_redirects=False,
        )
        pending = parse_qs(urlparse(callback.headers["location"]).query)["pending"][0]
        cancelled = await client.post(
            "/oauth/consent",
            data={"pending": pending, "action": "cancel"},
            follow_redirects=False,
        )
        assert cancelled.status_code == 302
        cancelled_query = parse_qs(urlparse(cancelled.headers["location"]).query)
        assert cancelled_query["error"] == ["access_denied"]
        assert cancelled_query["state"] == ["oauth-state"]


@pytest.mark.asyncio
async def test_google_consent_rejects_a_different_browser() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={"sub": "bound-sub", "email": "new@example.com", "email_verified": True},
        )

    settings = _settings()
    application = _google_app(settings, handler)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        client_id = await _register(client)
        _, query = await _start_google(client, client_id)
        callback = await client.get(
            "/oauth/google/callback",
            params={"code": "code", "state": parse_qs(query)["state"][0]},
            follow_redirects=False,
        )
        pending = parse_qs(urlparse(callback.headers["location"]).query)["pending"][0]
        client.cookies.clear()
        missing = await client.get("/oauth/consent", params={"pending": pending})
        assert missing.status_code == 400
        assert missing.json()["detail"] == "Authorization session does not match this browser"

        client.cookies.set("mt_oauth_browser", "wrong-browser")
        wrong = await client.get("/oauth/consent", params={"pending": pending})
        assert wrong.status_code == 400
        assert wrong.json()["detail"] == "Authorization session does not match this browser"

    async with SessionLocal() as session:
        assert await session.scalar(select(OAuthAuthCode)) is None


@pytest.mark.asyncio
async def test_google_callback_without_consent_rejects_a_different_browser() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={"sub": "bypass-bound-sub", "email": "new@example.com", "email_verified": True},
        )

    settings = _settings(oauth_require_consent=False)
    application = _google_app(settings, handler)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        client_id = await _register(client)
        _, query = await _start_google(client, client_id)
        client.cookies.clear()
        response = await client.get(
            "/oauth/google/callback",
            params={"code": "code", "state": parse_qs(query)["state"][0]},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "Authorization session does not match this browser"


@pytest.mark.asyncio
async def test_google_consent_can_be_disabled() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(GOOGLE_TOKEN_URL):
            return httpx.Response(200, json={"access_token": "token"})
        return httpx.Response(
            200,
            json={"sub": "bypass-sub", "email": "new@example.com", "email_verified": True},
        )

    settings = _settings(oauth_require_consent=False)
    application = _google_app(settings, handler)
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        client_id = await _register(client)
        verifier, query = await _start_google(client, client_id)
        callback = await client.get(
            "/oauth/google/callback",
            params={"code": "code", "state": parse_qs(query)["state"][0]},
            follow_redirects=False,
        )
        assert callback.status_code == 302
        redirect = urlparse(callback.headers["location"])
        assert redirect.path == "/callback"
        code = parse_qs(redirect.query)["code"][0]
        token = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "code": code,
                "redirect_uri": "https://client.example/callback",
                "code_verifier": verifier,
            },
        )
        assert token.status_code == 200


@pytest.mark.asyncio
async def test_google_missing_configuration_returns_503() -> None:
    settings = _settings(google_client_id="", google_client_secret="")
    provider = DbOAuthProvider()
    google = GoogleIdentityProvider(provider, settings)
    async with SessionLocal() as session:
        pending = OAuthPendingAuth(
            client_id="client",
            scopes=["mcp"],
            code_challenge="challenge",
            redirect_uri="https://client.example/callback",
            redirect_uri_provided_explicitly=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(pending)
        await session.commit()
        pending_id = pending.id
    route = create_login_route(provider, google, settings)
    application = Starlette(routes=[route])
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url=settings.public_base_url
    ) as client:
        response = await client.get("/oauth/login", params={"pending": str(pending_id)})
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_account_endpoints_update_timezone(client: AsyncClient) -> None:
    user, raw_token = await create_identity("account@example.com")
    headers = {"Authorization": f"Bearer {raw_token}"}
    response = await client.get("/api/me", headers=headers)
    assert response.status_code == 200
    assert response.json() == {
        "id": str(user.id),
        "email": "account@example.com",
        "timezone": "America/Sao_Paulo",
    }
    updated = await client.patch("/api/me", headers=headers, json={"timezone": "Europe/Lisbon"})
    assert updated.status_code == 200
    assert updated.json()["timezone"] == "Europe/Lisbon"
    invalid = await client.patch("/api/me", headers=headers, json={"timezone": "not/a/timezone"})
    assert invalid.status_code == 422
