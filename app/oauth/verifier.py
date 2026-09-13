from __future__ import annotations

from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.db import SessionLocal
from app.oauth.provider import DbOAuthProvider
from app.security import resolve_token


class CompositeTokenVerifier(TokenVerifier):
    def __init__(self, provider: DbOAuthProvider) -> None:
        self.provider = provider

    async def verify_token(self, token: str) -> AccessToken | None:
        oauth_token = await self.provider.load_access_token(token)
        if oauth_token is not None:
            return oauth_token
        async with SessionLocal() as session:
            user = await resolve_token(session, token)
        if user is None:
            return None
        return AccessToken(
            token=token,
            client_id="legacy-api-token",
            scopes=["mcp"],
            subject=str(user.id),
        )
