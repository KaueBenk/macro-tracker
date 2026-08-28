from __future__ import annotations

import os
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route

from app.config import Settings
from app.db import SessionLocal
from app.models import User
from app.oauth.provider import DbOAuthProvider


class IdentityProvider(Protocol):
    async def resolve_user(self, request: Request) -> User | None:
        """Resolve the human resource owner for an authorization request."""


class DevIdentityProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def resolve_user(self, request: Request) -> User | None:
        if self.settings.app_env.lower() == "production":
            return None
        email = request.query_params.get("email") or os.getenv("DEV_LOGIN_EMAIL")
        if not email:
            return None
        async with SessionLocal() as session:
            result = await session.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()


def create_login_route(
    provider: DbOAuthProvider, identity_provider: IdentityProvider, settings: Settings
) -> Route:
    async def login(request: Request) -> RedirectResponse | JSONResponse:
        pending_value = request.query_params.get("pending")
        if pending_value is None:
            return JSONResponse({"detail": "Missing pending authorization"}, status_code=400)
        try:
            pending_id = UUID(pending_value)
        except ValueError:
            return JSONResponse({"detail": "Invalid pending authorization"}, status_code=400)
        user = await identity_provider.resolve_user(request)
        if user is None:
            if settings.app_env.lower() == "production":
                return JSONResponse(
                    {"detail": "OAuth login is not configured in production"}, status_code=503
                )
            return JSONResponse(
                {"detail": "Development login requires a valid email"}, status_code=401
            )
        redirect_uri = await provider.complete_pending_authorization(pending_id, user.id)
        if redirect_uri is None:
            return JSONResponse(
                {"detail": "Pending authorization is invalid or expired"}, status_code=400
            )
        return RedirectResponse(
            redirect_uri, status_code=302, headers={"Cache-Control": "no-store"}
        )

    return Route("/oauth/login", login, methods=["GET"])
