from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = the directory containing main.py (two levels up from this
# file: bot/config.py -> bot/ -> <root>). Every path-like setting below is
# anchored here instead of the current working directory, so the bot
# behaves identically whether it's started with `python main.py` from the
# project folder or launched by systemd with a different WorkingDirectory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file.

    No secrets ever live in code — everything comes from the environment.
    """

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    BOT_TOKEN: str
    # Kept as a raw comma-separated string (not List[int]) on purpose:
    # pydantic-settings treats List[...]-typed env fields as JSON and tries
    # to json.loads() them before any validator runs, which breaks a plain
    # "123,456" value. Parsing is done ourselves in `admin_ids` below.
    ADMIN_IDS: str
    DATABASE_URL: str = "sqlite+aiosqlite:///bot.db"
    TIMEZONE: str = "Asia/Tashkent"
    REMINDER_HOURS_BEFORE: int = 2

    @field_validator("BOT_TOKEN")
    @classmethod
    def _validate_token(cls, value: str) -> str:
        if not value or ":" not in value:
            raise ValueError("BOT_TOKEN looks invalid — check your .env file")
        return value

    @field_validator("ADMIN_IDS")
    @classmethod
    def _validate_admin_ids(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ADMIN_IDS must contain at least one Telegram user ID")
        for part in value.split(","):
            if not part.strip().isdigit():
                raise ValueError(f"ADMIN_IDS contains an invalid user ID: {part!r}")
        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def _resolve_relative_sqlite_path(cls, value: str) -> str:
        """A relative sqlite path (`sqlite+aiosqlite:///bot.db`, 3 slashes)
        is resolved by the sqlite driver against the current working
        directory. Anchor it to PROJECT_ROOT instead, so the DB file is
        always found/created in the same place regardless of where the
        process was started from. Absolute sqlite paths (4 slashes) and
        every other backend (e.g. postgresql+asyncpg://...) pass through
        unchanged.
        """
        prefix = "sqlite+aiosqlite:///"
        if value.startswith(prefix):
            relative_part = value[len(prefix) :]
            if relative_part and not relative_part.startswith("/") and relative_part != ":memory:":
                absolute_path = (PROJECT_ROOT / relative_part).resolve()
                return f"{prefix}{absolute_path.as_posix()}"
        return value

    @cached_property
    def admin_ids(self) -> List[int]:
        return [int(part.strip()) for part in self.ADMIN_IDS.split(",") if part.strip()]


settings = Settings()
