from contextvars import ContextVar
from typing import cast
from uuid import UUID

from mcp.server.auth.provider import TokenVerifier
from pydantic import AnyHttpUrl
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

current_user_id: ContextVar[UUID | None] = ContextVar("current_user_id", default=None)


class BearerAuthMiddleware:
    def __init__(
        self, app: ASGIApp, token_verifier: TokenVerifier, resource_metadata_url: AnyHttpUrl
    ) -> None:
        self.app = app
        self.token_verifier = token_verifier
        self.resource_metadata_url = resource_metadata_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        authorization = next(
            (
                value.decode("latin-1")
                for key, value in scope.get("headers", [])
                if key == b"authorization"
            ),
            None,
        )
        if authorization is None or not authorization.lower().startswith("bearer "):
            await self._unauthorized(scope, receive, send)
            return
        raw_token = authorization[7:].strip()
        if not raw_token:
            await self._unauthorized(scope, receive, send)
            return
        token_info = await self.token_verifier.verify_token(raw_token)
        if token_info is None or token_info.subject is None:
            await self._unauthorized(scope, receive, send)
            return
        try:
            user_id = UUID(token_info.subject)
        except ValueError:
            await self._unauthorized(scope, receive, send)
            return
        token = current_user_id.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_id.reset(token)

    async def _unauthorized(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": "Invalid or missing token"},
            status_code=401,
            headers={
                "WWW-Authenticate": (
                    f'Bearer error="invalid_token", '
                    f'error_description="Authentication required", '
                    f'resource_metadata="{self.resource_metadata_url}"'
                )
            },
        )
        await response(scope, receive, send)


class MCPPathAdapter:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in {"/mcp", "/mcp/", ""}:
            scope = cast(Scope, dict(scope))
            scope["path"] = "/"
            scope["raw_path"] = b"/"
        await self.app(scope, receive, send)
