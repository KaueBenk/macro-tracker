import os
from functools import lru_cache

from mcp.server.auth.settings import (
    AuthSettings as MCPAuthSettings,
)
from mcp.server.auth.settings import (
    ClientRegistrationOptions,
    RevocationOptions,
)
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


def _default_serverless() -> bool:
    return os.getenv("VERCEL") is not None


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/macro_tracker_test"
    app_env: str = "development"
    default_timezone: str = "America/Sao_Paulo"
    log_level: str = "INFO"
    public_base_url: str = "http://localhost:8000"
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_emails: str = ""
    oauth_require_consent: bool = True
    food_provider_sources: str = ""
    usda_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("USDA_FDC_API_KEY", "USDA_API_KEY"),
    )
    off_user_agent: str = "macro-tracker/0.1 (https://github.com/KaueBenk/macro-tracker)"
    tbca_detail_limit: int = 5
    provider_timeout_seconds: float = 5.0
    fatsecret_client_id: str = ""
    fatsecret_client_secret: str = ""
    fatsecret_detail_limit: int = 5
    serverless: bool = Field(default_factory=_default_serverless)

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        url = make_url(value)
        if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
            return value
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+asyncpg")
        query = dict(url.query)
        sslmode = query.pop("sslmode", None)
        query.pop("channel_binding", None)
        if sslmode is not None:
            query["ssl"] = sslmode
        return url.set(query=query).render_as_string(hide_password=False)

    @field_validator("public_base_url", mode="before")
    @classmethod
    def normalize_public_base_url(cls, value: str) -> str:
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_auth_settings() -> MCPAuthSettings:
    settings = get_settings()
    base_url = settings.public_base_url
    return MCPAuthSettings(
        issuer_url=base_url,
        resource_server_url=f"{base_url}/mcp",
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["mcp", "ACCESS_VIEW_MANAGE_MCP_CONTENT"],
            default_scopes=["mcp", "ACCESS_VIEW_MANAGE_MCP_CONTENT"],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=None,
    )


def get_allowed_emails(settings: Settings) -> set[str]:
    return {email.strip().lower() for email in settings.allowed_emails.split(",") if email.strip()}
