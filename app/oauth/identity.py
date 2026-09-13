from __future__ import annotations

import html
import os
import secrets
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from app.config import Settings
from app.db import SessionLocal
from app.models import OAuthPendingAuth, User
from app.oauth.provider import DbOAuthProvider
from app.security import create_token, hash_token


class IdentityProvider(Protocol):
    async def resolve_user(self, request: Request) -> User | None:
        """Resolve the human resource owner for an authorization request."""


@runtime_checkable
class OAuthLoginStarter(Protocol):
    async def begin_login(self, pending_id: UUID) -> Response:
        """Start an external identity-provider login."""


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
    async def login(request: Request) -> Response:
        pending_value = request.query_params.get("pending")
        if pending_value is None:
            return JSONResponse({"detail": "Missing pending authorization"}, status_code=400)
        try:
            pending_id = UUID(pending_value)
        except ValueError:
            return JSONResponse({"detail": "Invalid pending authorization"}, status_code=400)
        if isinstance(identity_provider, OAuthLoginStarter):
            raw_browser_token, browser_hash = create_token()
            if not await provider.set_browser_hash(pending_id, browser_hash):
                return JSONResponse(
                    {"detail": "Pending authorization is invalid or expired"}, status_code=400
                )
            response = await identity_provider.begin_login(pending_id)
            response.set_cookie(
                "mt_oauth_browser",
                raw_browser_token,
                max_age=600,
                path="/",
                secure=True,
                httponly=True,
                samesite="lax",
            )
            return response
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


def _consent_page(pending: OAuthPendingAuth, client_name: str) -> str:
    safe_name = html.escape(client_name)
    return f"""<!doctype html>
<html lang="pt-BR">
  <head><meta charset="utf-8"><title>Autorizar acesso</title></head>
  <body>
    <h1>Autorizar acesso</h1>
    <p><strong>{safe_name}</strong> quer acessar seus dados de macronutrientes.</p>
    <p>O aplicativo poderá consultar e gerenciar seus alimentos, registros,
    metas e resumos por meio do servidor MCP.</p>
    <form method="post">
      <input type="hidden" name="pending" value="{pending.id}">
      <button type="submit" name="action" value="authorize">Autorizar</button>
      <button type="submit" name="action" value="cancel">Cancelar</button>
    </form>
  </body>
</html>"""


def create_consent_routes(provider: DbOAuthProvider) -> list[Route]:
    async def consent(request: Request) -> HTMLResponse | RedirectResponse | JSONResponse:
        pending_value = request.query_params.get("pending")
        if request.method == "POST":
            form = await request.form()
            pending_value = str(form.get("pending") or pending_value or "")
            action = str(form.get("action") or "")
        else:
            action = ""
        try:
            pending_id = UUID(pending_value)
        except ValueError:
            return JSONResponse({"detail": "Invalid pending authorization"}, status_code=400)
        pending = await provider.get_pending(pending_id)
        if pending is None or pending.expires_at <= datetime.now(UTC):
            return JSONResponse(
                {"detail": "Pending authorization is invalid or expired"}, status_code=400
            )
        if not browser_matches(request, pending):
            return JSONResponse(
                {"detail": "Authorization session does not match this browser"},
                status_code=400,
            )
        client = await provider.get_client(pending.client_id)
        client_name = client.client_name if client and client.client_name else pending.client_id
        if request.method == "GET":
            return HTMLResponse(_consent_page(pending, client_name))
        if action == "cancel":
            redirect_uri = await provider.cancel_pending_authorization(pending_id)
            if redirect_uri is None:
                return JSONResponse(
                    {"detail": "Pending authorization is invalid or expired"}, status_code=400
                )
            response = RedirectResponse(redirect_uri, status_code=302)
            response.delete_cookie("mt_oauth_browser", path="/")
            return response
        if action != "authorize" or pending.user_id is None:
            return JSONResponse({"detail": "Authorization is required"}, status_code=400)
        redirect_uri = await provider.complete_pending_authorization(pending_id, pending.user_id)
        if redirect_uri is None:
            return JSONResponse(
                {"detail": "Pending authorization is invalid or expired"}, status_code=400
            )
        response = RedirectResponse(
            redirect_uri, status_code=302, headers={"Cache-Control": "no-store"}
        )
        response.delete_cookie("mt_oauth_browser", path="/")
        return response

    return [
        Route("/oauth/consent", consent, methods=["GET", "POST"]),
    ]


def browser_matches(request: Request, pending: OAuthPendingAuth) -> bool:
    if pending.browser_hash is None:
        return True
    browser_token = request.cookies.get("mt_oauth_browser")
    if browser_token is None:
        return False
    return secrets.compare_digest(pending.browser_hash, hash_token(browser_token))
