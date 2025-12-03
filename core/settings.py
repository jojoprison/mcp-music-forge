from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = Field(default="dev", alias="APP_ENV")
    tz: str = Field(default="UTC", alias="TZ")

    redis_url: str = Field(
        default="redis://localhost:6379/0", alias="REDIS_URL"
    )

    storage_dir: Path = Field(default=Path("data"), alias="STORAGE_DIR")

    database_url: str = Field(
        default="sqlite:///data/db.sqlite3", alias="DATABASE_URL"
    )

    soundcloud_cookie_file: Path | None = Field(
        default=None, alias="SOUNDCLOUD_COOKIE_FILE"
    )

    # If true, allow stream downloads even when provider marks not downloadable
    allow_stream_downloads: bool = Field(
        default=True, alias="ALLOW_STREAM_DOWNLOADS"
    )

    ffmpeg_bin: str = Field(default="ffmpeg", alias="FFMPEG_BIN")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8033, alias="API_PORT")

    # OTEL
    otel_endpoint: str | None = Field(
        default=None, alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otel_service_name: str = Field(
        default="mcp-music-forge", alias="OTEL_SERVICE_NAME"
    )

    # Telegram Bot
    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")


class RuntimeContext(BaseModel):
    settings: AppSettings


@lru_cache
def get_settings() -> AppSettings:
    s = AppSettings()
    # Ensure storage dir exists
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    # Ensure db dir exists for sqlite
    if s.database_url.startswith("sqlite"):
        Path("data").mkdir(parents=True, exist_ok=True)
    return s
