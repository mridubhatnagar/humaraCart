"""App configuration — pydantic-settings, env-driven (CLAUDE.md: never hardcode secrets)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite:///./data/humaracart.db"
    token_encryption_key: str

    twilio_account_sid: str
    twilio_auth_token: str
    twilio_whatsapp_from: str

    jwt_secret: str
    oauth_redirect_uri: str

    openai_api_key: str
    openai_model: str


@lru_cache
def get_settings() -> Settings:
    return Settings()
