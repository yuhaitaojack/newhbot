from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process/infrastructure config only. Trading knobs live in SQLite."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/newhbot.db"
    execution_worker_url: str = "http://127.0.0.1:8001"
    execution_worker_write_timeout_seconds: float = 60.0
    execution_worker_read_timeout_seconds: float = 10.0
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"
    execution_mode: str = "mock"
    strategies_dir: str = "strategies/versions"
    control_api_token: str | None = None
    database_backup_path: str | None = None
    database_backup_interval_seconds: float = 300.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


def get_settings() -> Settings:
    return Settings()
