"""Domain-neutral runtime configuration."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the platform, overridable via environment.

    Environment variables use the ``HYBRID_KG_`` prefix (e.g. ``HYBRID_KG_LOG_LEVEL``).
    """

    model_config = SettingsConfigDict(
        env_prefix="HYBRID_KG_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "hybrid-kg"
    log_level: str = "INFO"
    log_format: str = "json"


def load_settings() -> Settings:
    """Load settings from environment and defaults."""
    return Settings()
