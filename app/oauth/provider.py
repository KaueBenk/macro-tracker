from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import OAuthAuthCode, OAuthClient, OAuthPendingAuth
from app.models import OAuthToken as OAuthTokenRecord
from app.security import create_token, hash_token


class DbRefreshToken(RefreshToken):
    resource: str | None = None


class DbOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, DbRefreshToken, AccessToken]
):
    authorization_code_ttl = timedelta(seconds=600)
    access_token_ttl = timedelta(seconds=3600)
    refresh_token_ttl = timedelta(days=30)

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with SessionLocal() as session:
            record = await session.get(OAuthClient, client_id)
            if record is None:
                return None
            return OAuthClientInformationFull.model_validate(
                {**record.client_metadata, "client_secret": record.client_secret}
            )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        client_metadata = cast(dict[str, object], client_info.model_dump(mode="json"))
        client_secret = client_info.client_secret
        client_metadata.pop("client_secret", None)
        async with SessionLocal() as session:
            session.add(
                OAuthClient(
                    client_id=client_info.client_id,
                    client_secret=client_secret,
                    client_metadata=client_metadata,
                )
            )
            await session.commit()

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        async with SessionLocal() as session:
            pending = OAuthPendingAuth(
                client_id=client.client_id,
                state=params.state,
                login_state=None,
                user_id=None,
                scopes=params.scopes or (client.scope.split() if client.scope else []),
                code_challenge=params.code_challenge,
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=params.resource,
                expires_at=datetime.now(UTC) + self.authorization_code_ttl,
            )
            session.add(pending)
            await session.flush()
            pending_id = pending.id
            await session.commit()
        return f"{get_settings().public_base_url}/oauth/login?pending={pending_id}"

    async def set_login_state(self, pending_id: UUID, login_state: str) -> bool:
        async with SessionLocal() as session:
            pending = await session.get(OAuthPendingAuth, pending_id, with_for_update=True)
            if pending is None or pending.expires_at <= datetime.now(UTC):
                return False
            pending.login_state = login_state
            await session.commit()
            return True

    async def get_pending_by_login_state(self, login_state: str) -> OAuthPendingAuth | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(OAuthPendingAuth).where(OAuthPendingAuth.login_state == login_state)
            )
            return result.scalar_one_or_none()

    async def set_pending_user(self, pending_id: UUID, user_id: UUID) -> bool:
        async with SessionLocal() as session:
            pending = await session.get(OAuthPendingAuth, pending_id, with_for_update=True)
            if pending is None or pending.expires_at <= datetime.now(UTC):
                return False
            pending.user_id = user_id
            pending.login_state = None
            await session.commit()
            return True

    async def get_pending(self, pending_id: UUID) -> OAuthPendingAuth | None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(OAuthPendingAuth).where(OAuthPendingAuth.id == pending_id)
            )
            return result.scalar_one_or_none()

    async def cancel_pending_authorization(self, pending_id: UUID) -> str | None:
        async with SessionLocal() as session:
            pending = await session.scalar(
                select(OAuthPendingAuth).where(OAuthPendingAuth.id == pending_id).with_for_update()
            )
            if pending is None or pending.expires_at <= datetime.now(UTC):
                return None
            redirect_uri = construct_redirect_uri(
                pending.redirect_uri,
                error="access_denied",
                state=pending.state,
            )
            await session.delete(pending)
            await session.commit()
            return redirect_uri

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code_hash = hash_token(authorization_code)
        async with SessionLocal() as session:
            record = await session.get(OAuthAuthCode, code_hash)
            if (
                record is None
                or record.client_id != client.client_id
                or record.consumed_at is not None
                or record.expires_at <= datetime.now(UTC)
            ):
                return None
            return AuthorizationCode(
                code=authorization_code,
                client_id=record.client_id,
                scopes=list(record.scopes),
                expires_at=record.expires_at.timestamp(),
                code_challenge=record.code_challenge,
                redirect_uri=record.redirect_uri,
                redirect_uri_provided_explicitly=record.redirect_uri_provided_explicitly,
                resource=record.resource,
                subject=str(record.user_id),
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        code_hash = hash_token(authorization_code.code)
        async with SessionLocal() as session:
            record = await session.scalar(
                select(OAuthAuthCode)
                .where(
                    OAuthAuthCode.code_hash == code_hash,
                    OAuthAuthCode.client_id == client.client_id,
                )
                .with_for_update()
            )
            if (
                record is None
                or record.consumed_at is not None
                or record.expires_at <= datetime.now(UTC)
            ):
                raise TokenError(
                    error="invalid_grant", error_description="Authorization code is invalid"
                )
            record.consumed_at = datetime.now(UTC)
            tokens = self._create_token_pair(
                session,
                client_id=record.client_id,
                user_id=record.user_id,
                scopes=list(record.scopes),
                resource=record.resource,
                refresh_parent_hash=None,
            )
            await session.commit()
            return tokens

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> DbRefreshToken | None:
        token_hash = hash_token(refresh_token)
        async with SessionLocal() as session:
            record = await session.get(OAuthTokenRecord, token_hash)
            if (
                record is None
                or record.kind != "refresh"
                or record.client_id != client.client_id
                or record.revoked_at is not None
                or record.expires_at <= datetime.now(UTC)
            ):
                return None
            return DbRefreshToken(
                token=refresh_token,
                client_id=record.client_id,
                scopes=list(record.scopes),
                expires_at=int(record.expires_at.timestamp()),
                subject=str(record.user_id),
                resource=record.resource,
            )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: DbRefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        token_hash = hash_token(refresh_token.token)
        async with SessionLocal() as session:
            record = await session.scalar(
                select(OAuthTokenRecord)
                .where(
                    OAuthTokenRecord.token_hash == token_hash,
                    OAuthTokenRecord.kind == "refresh",
                    OAuthTokenRecord.client_id == client.client_id,
                )
                .with_for_update()
            )
            if (
                record is None
                or record.revoked_at is not None
                or record.expires_at <= datetime.now(UTC)
            ):
                raise TokenError(
                    error="invalid_grant", error_description="Refresh token is invalid"
                )
            record.revoked_at = datetime.now(UTC)
            tokens = self._create_token_pair(
                session,
                client_id=record.client_id,
                user_id=record.user_id,
                scopes=scopes,
                resource=record.resource,
                refresh_parent_hash=token_hash,
            )
            await session.commit()
            return tokens

    async def load_access_token(self, token: str) -> AccessToken | None:
        token_hash = hash_token(token)
        async with SessionLocal() as session:
            record = await session.get(OAuthTokenRecord, token_hash)
            if (
                record is None
                or record.kind != "access"
                or record.revoked_at is not None
                or record.expires_at <= datetime.now(UTC)
            ):
                return None
            return AccessToken(
                token=token,
                client_id=record.client_id,
                scopes=list(record.scopes),
                expires_at=int(record.expires_at.timestamp()),
                resource=record.resource,
                subject=str(record.user_id),
            )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_hash = hash_token(token.token)
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            record = await session.get(OAuthTokenRecord, token_hash)
            if record is None:
                return
            record.revoked_at = now
            if record.kind == "access" and record.parent_hash is not None:
                refresh = await session.get(OAuthTokenRecord, record.parent_hash)
                if refresh is not None:
                    refresh.revoked_at = now
            elif record.kind == "refresh":
                access = await session.scalar(
                    select(OAuthTokenRecord).where(
                        OAuthTokenRecord.parent_hash == record.token_hash,
                        OAuthTokenRecord.kind == "access",
                    )
                )
                if access is not None:
                    access.revoked_at = now
            await session.commit()

    async def complete_pending_authorization(self, pending_id: UUID, user_id: UUID) -> str | None:
        raw_code, code_hash = create_token()
        async with SessionLocal() as session:
            pending = await session.scalar(
                select(OAuthPendingAuth).where(OAuthPendingAuth.id == pending_id).with_for_update()
            )
            if pending is None or pending.expires_at <= datetime.now(UTC):
                return None
            session.add(
                OAuthAuthCode(
                    code_hash=code_hash,
                    client_id=pending.client_id,
                    user_id=user_id,
                    scopes=list(pending.scopes),
                    code_challenge=pending.code_challenge,
                    redirect_uri=pending.redirect_uri,
                    redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
                    resource=pending.resource,
                    expires_at=datetime.now(UTC) + self.authorization_code_ttl,
                )
            )
            redirect_uri = pending.redirect_uri
            state = pending.state
            await session.delete(pending)
            await session.commit()
        return construct_redirect_uri(redirect_uri, code=raw_code, state=state)

    def _create_token_pair(
        self,
        session: AsyncSession,
        client_id: str,
        user_id: UUID,
        scopes: list[str],
        resource: str | None,
        refresh_parent_hash: str | None,
    ) -> OAuthToken:
        raw_access, access_hash = create_token()
        raw_refresh, refresh_hash = create_token()
        now = datetime.now(UTC)
        session.add(
            OAuthTokenRecord(
                token_hash=access_hash,
                kind="access",
                client_id=client_id,
                user_id=user_id,
                scopes=list(scopes),
                resource=resource,
                expires_at=now + self.access_token_ttl,
                parent_hash=refresh_hash,
            )
        )
        session.add(
            OAuthTokenRecord(
                token_hash=refresh_hash,
                kind="refresh",
                client_id=client_id,
                user_id=user_id,
                scopes=list(scopes),
                resource=resource,
                expires_at=now + self.refresh_token_ttl,
                parent_hash=refresh_parent_hash,
            )
        )
        return OAuthToken(
            access_token=raw_access,
            expires_in=int(self.access_token_ttl.total_seconds()),
            refresh_token=raw_refresh,
            scope=" ".join(scopes),
        )
