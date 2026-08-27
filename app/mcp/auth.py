from contextvars import ContextVar
from uuid import UUID

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.db import SessionLocal
from app.security import resolve_token

current_user_id: ContextVar[UUID | None] = ContextVar("current_user_id", default=None)


class BearerAuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

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
            await JSONResponse({"detail": "Invalid or missing token"}, status_code=401)(
                scope, receive, send
            )
            return
        raw_token = authorization[7:].strip()
        if not raw_token:
            await JSONResponse({"detail": "Invalid or missing token"}, status_code=401)(
                scope, receive, send
            )
            return
        async with SessionLocal() as session:
            user = await resolve_token(session, raw_token)
        if user is None:
            await JSONResponse({"detail": "Invalid or missing token"}, status_code=401)(
                scope, receive, send
            )
            return
        token = current_user_id.set(user.id)
        try:
            await self.app(scope, receive, send)
        finally:
            current_user_id.reset(token)
