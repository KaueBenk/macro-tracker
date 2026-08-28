import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from starlette.applications import Starlette

from app.config import Settings
from app.db import SessionLocal
from app.models import OAuthClient, OAuthPendingAuth
from app.oauth.identity import DevIdentityProvider, create_login_route
from app.oauth.provider import DbOAuthProvider
from tests.conftest import create_identity


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _path(url: str) -> str:
    parsed = urlparse(url)
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


@pytest.mark.asyncio
async def test_oauth_metadata_and_protected_resource(client: AsyncClient) -> None:
    metadata = await client.get("/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    body = metadata.json()
    assert body["issuer"] == "http://localhost:8000"
    assert body["authorization_endpoint"] == "http://localhost:8000/authorize"
    assert body["token_endpoint"] == "http://localhost:8000/token"
    assert body["registration_endpoint"] == "http://localhost:8000/register"
    assert body["revocation_endpoint"] == "http://localhost:8000/revoke"
    assert body["scopes_supported"] == ["mcp", "ACCESS_VIEW_MANAGE_MCP_CONTENT"]
    assert body["code_challenge_methods_supported"] == ["S256"]

    resource = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert resource.status_code == 200
    resource_body = resource.json()
    assert resource_body["resource"] == "http://localhost:8000/mcp"
    assert resource_body["authorization_servers"] == ["http://localhost:8000"]
    assert resource_body["scopes_supported"] == ["mcp", "ACCESS_VIEW_MANAGE_MCP_CONTENT"]


@pytest.mark.asyncio
async def test_oauth_authorization_code_pkce_refresh_and_revoke(client: AsyncClient) -> None:
    user, _ = await create_identity("oauth@example.com")
    registration = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "scope": "mcp ACCESS_VIEW_MANAGE_MCP_CONTENT",
        },
    )
    assert registration.status_code == 201
    client_info = registration.json()
    client_id = client_info["client_id"]

    verifier = "verifier-for-oauth-flow"
    authorization = await client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
            "scope": "mcp ACCESS_VIEW_MANAGE_MCP_CONTENT",
            "state": "state-value",
            "resource": "http://localhost:8000/mcp",
        },
    )
    assert authorization.status_code == 302
    login_url = authorization.headers["location"]
    login = await client.get(
        _path(login_url) + "&email=oauth@example.com",
        follow_redirects=False,
    )
    assert login.status_code == 302
    callback = urlparse(login.headers["location"])
    callback_params = parse_qs(callback.query)
    assert callback_params["state"] == ["state-value"]
    code = callback_params["code"][0]

    token_response = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": "https://client.example/callback",
            "code_verifier": verifier,
        },
    )
    assert token_response.status_code == 200
    tokens = token_response.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]
    assert tokens["scope"] == "mcp ACCESS_VIEW_MANAGE_MCP_CONTENT"

    reused = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": "https://client.example/callback",
            "code_verifier": verifier,
        },
    )
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"

    wrong_registration = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
            "scope": "unknown",
        },
    )
    assert wrong_registration.status_code == 400

    wrong_verifier = await client.post(
        "/register",
        json={
            "redirect_uris": ["https://client.example/callback"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert wrong_verifier.status_code == 201
    wrong_client_id = wrong_verifier.json()["client_id"]
    wrong_auth = await client.get(
        "/authorize",
        params={
            "client_id": wrong_client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
        },
    )
    wrong_login = await client.get(
        _path(wrong_auth.headers["location"]) + "&email=oauth@example.com",
        follow_redirects=False,
    )
    wrong_code = parse_qs(urlparse(wrong_login.headers["location"]).query)["code"][0]
    invalid_pkce = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": wrong_client_id,
            "code": wrong_code,
            "redirect_uri": "https://client.example/callback",
            "code_verifier": "incorrect-verifier",
        },
    )
    assert invalid_pkce.status_code == 400
    assert invalid_pkce.json()["error"] == "invalid_grant"

    refresh = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
    )
    assert refresh.status_code == 200
    rotated = refresh.json()
    assert rotated["refresh_token"] != refresh_token
    old_refresh = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        },
    )
    assert old_refresh.status_code == 400
    assert old_refresh.json()["error"] == "invalid_grant"

    revoked = await client.post(
        "/revoke",
        data={"client_id": client_id, "client_secret": "", "token": rotated["access_token"]},
    )
    assert revoked.status_code == 200

    authenticated = await DbOAuthProvider().load_access_token(access_token)
    assert authenticated is not None
    assert authenticated.subject == str(user.id)


@pytest.mark.asyncio
async def test_mcp_missing_token_advertises_resource_metadata(client: AsyncClient) -> None:
    response = await client.post("/mcp", json={})
    assert response.status_code == 401
    assert (
        response.headers["www-authenticate"]
        == 'Bearer error="invalid_token", error_description="Authentication required", '
        "resource_metadata="
        '"http://localhost:8000/.well-known/oauth-protected-resource/mcp"'
    )


@pytest.mark.asyncio
async def test_confidential_client_secret_is_stored_separately_and_authenticates(
    client: AsyncClient,
) -> None:
    await create_identity("confidential@example.com")
    registration = await client.post(
        "/register",
        json={"redirect_uris": ["https://client.example/callback"]},
    )
    assert registration.status_code == 201
    info = registration.json()
    client_id = info["client_id"]
    client_secret = info["client_secret"]
    async with SessionLocal() as session:
        record = await session.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
        assert record is not None
        assert record.client_secret == client_secret
        assert "client_secret" not in record.client_metadata

    verifier = "confidential-verifier"
    authorization = await client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://client.example/callback",
            "response_type": "code",
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
        },
    )
    login = await client.get(
        _path(authorization.headers["location"]) + "&email=confidential@example.com",
        follow_redirects=False,
    )
    code = parse_qs(urlparse(login.headers["location"]).query)["code"][0]
    token = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": "https://client.example/callback",
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200


@pytest.mark.asyncio
async def test_dev_identity_provider_is_unavailable_in_production() -> None:
    async with SessionLocal() as session:
        pending = OAuthPendingAuth(
            client_id="production-test",
            scopes=["mcp"],
            code_challenge="challenge",
            redirect_uri="https://client.example/callback",
            redirect_uri_provided_explicitly=True,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        session.add(pending)
        await session.flush()
        pending_id = pending.id
        await session.commit()

    settings = Settings(app_env="production")
    route = create_login_route(
        DbOAuthProvider(),
        DevIdentityProvider(settings),
        settings,
    )
    production_app = Starlette(routes=[route])
    async with AsyncClient(
        transport=ASGITransport(app=production_app),
        base_url="http://test",
    ) as production_client:
        response = await production_client.get(f"/oauth/login?pending={pending_id}")
    assert response.status_code == 503
    assert response.json()["detail"] == "OAuth login is not configured in production"
