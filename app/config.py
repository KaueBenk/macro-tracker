import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_serverless() -> bool:
    return os.getenv("VERCEL") is not None


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/macro_tracker_test"
    app_env: str = "development"
    default_timezone: str = "America/Sao_Paulo"
    log_level: str = "INFO"
    serverless: bool = Field(default_factory=_default_serverless)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
