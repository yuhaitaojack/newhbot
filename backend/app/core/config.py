from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process/infrastructure config only. Trading knobs live in SQLite."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/newhbot.db"
    execution_worker_url: str = "http://127.0.0.1:8001"
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    execution_mode: str = "mock"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


def get_settings() -> Settings:
    return Settings()
