from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy import func, select
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from app.config import Settings, get_allowed_emails
from app.db import SessionLocal
from app.models import OAuthPendingAuth, User
from app.oauth.identity import IdentityProvider, OAuthLoginStarter
from app.oauth.provider import DbOAuthProvider

GOOGLE_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class GoogleIdentityError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail


class GoogleIdentityProvider(IdentityProvider, OAuthLoginStarter):
    def __init__(
        self,
        provider: DbOAuthProvider,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider = provider
        self.settings = settings
        self.transport = transport

    async def begin_login(self, pending_id: UUID) -> Response:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            return JSONResponse(
                {"detail": "Google OAuth login is not configured"},
                status_code=503,
            )
        login_state = secrets.token_urlsafe(32)
        if not await self.provider.set_login_state(pending_id, login_state):
            return JSONResponse(
                {"detail": "Pending authorization is invalid or expired"},
                status_code=400,
            )
        query = urlencode(
            {
                "client_id": self.settings.google_client_id,
                "redirect_uri": self.callback_uri,
                "response_type": "code",
                "scope": "openid email",
                "access_type": "online",
                "prompt": "select_account",
                "state": login_state,
            }
        )
        return RedirectResponse(
            f"{GOOGLE_AUTHORIZATION_URL}?{query}",
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )

    async def resolve_user(self, request: Request) -> User | None:
        try:
            _, user = await self.resolve_callback(request)
        except GoogleIdentityError:
            return None
        return user

    async def resolve_callback(self, request: Request) -> tuple[OAuthPendingAuth, User]:
        if not self.settings.google_client_id or not self.settings.google_client_secret:
            raise GoogleIdentityError(503, "Google OAuth login is not configured")
        code = request.query_params.get("code")
        login_state = request.query_params.get("state")
        if not code or not login_state:
            raise GoogleIdentityError(400, "Google callback requires code and state")
        pending = await self.provider.get_pending_by_login_state(login_state)
        if (
            pending is None
            or pending.expires_at <= datetime.now(UTC)
            or pending.login_state is None
            or not secrets.compare_digest(pending.login_state, login_state)
        ):
            raise GoogleIdentityError(400, "Invalid Google OAuth state")
        try:
            async with httpx.AsyncClient(transport=self.transport) as client:
                token_response = await client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "code": code,
                        "client_id": self.settings.google_client_id,
                        "client_secret": self.settings.google_client_secret,
                        "redirect_uri": self.callback_uri,
                        "grant_type": "authorization_code",
                    },
                )
                token_response.raise_for_status()
                token_data = _json_object(token_response)
                access_token = _string_value(token_data, "access_token")
                userinfo_response = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                userinfo_response.raise_for_status()
                profile = _json_object(userinfo_response)
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleIdentityError(502, "Google identity verification failed") from exc
        if profile.get("email_verified") is not True:
            raise GoogleIdentityError(403, "Google email is not verified")
        email = _string_value(profile, "email").lower()
        google_sub = _string_value(profile, "sub")
        user = await self._provision_user(email, google_sub)
        if not await self.provider.set_pending_user(pending.id, user.id):
            raise GoogleIdentityError(400, "Pending authorization is invalid or expired")
        pending.user_id = user.id
        return pending, user

    @property
    def callback_uri(self) -> str:
        return f"{self.settings.public_base_url}/oauth/google/callback"

    async def _provision_user(self, email: str, google_sub: str) -> User:
        async with SessionLocal() as session:
            user = await session.scalar(select(User).where(User.google_sub == google_sub))
            if user is None:
                user = await session.scalar(select(User).where(func.lower(User.email) == email))
            if user is None:
                if email not in get_allowed_emails(self.settings):
                    raise GoogleIdentityError(
                        403,
                        "New user registration is restricted to the configured allowlist",
                    )
                user = User(
                    email=email,
                    timezone=self.settings.default_timezone,
                    google_sub=google_sub,
                )
                session.add(user)
            else:
                user.google_sub = google_sub
            await session.commit()
            await session.refresh(user)
            return user


def _json_object(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Google response was not an object")
    return cast(dict[str, object], payload)


def _string_value(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Google response did not include {name}")
    return value


def create_google_callback_route(
    identity_provider: GoogleIdentityProvider,
    provider: DbOAuthProvider,
    settings: Settings,
) -> Route:
    async def callback(request: Request) -> Response:
        try:
            pending, _ = await identity_provider.resolve_callback(request)
        except GoogleIdentityError as exc:
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        if settings.oauth_require_consent:
            return RedirectResponse(
                f"{settings.public_base_url}/oauth/consent?pending={pending.id}",
                status_code=302,
                headers={"Cache-Control": "no-store"},
            )
        if pending.user_id is None:
            return JSONResponse(
                {"detail": "Pending authorization is invalid or expired"},
                status_code=400,
            )
        redirect_uri = await provider.complete_pending_authorization(pending.id, pending.user_id)
        if redirect_uri is None:
            return JSONResponse(
                {"detail": "Pending authorization is invalid or expired"},
                status_code=400,
            )
        return RedirectResponse(
            redirect_uri, status_code=302, headers={"Cache-Control": "no-store"}
        )

    return Route("/oauth/google/callback", callback, methods=["GET"])
