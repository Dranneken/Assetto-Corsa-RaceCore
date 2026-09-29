"""Runtime configuration loaded from environment variables."""

import os
import sys
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _environment_file() -> Path:
    configured_path = os.getenv("RACECORE_ENV_FILE")
    if configured_path:
        return Path(configured_path).expanduser()
    if getattr(sys, "frozen", False):
        local_app_data = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return local_app_data / "RaceCore" / ".env"
    return Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    database_url: str | None = None
    shutdown_token: str | None = None
    admin_username: str | None = None
    admin_password: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_prefix="RACECORE_",
        env_file=_environment_file(),
        extra="ignore",
    )


settings = Settings()
