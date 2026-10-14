"""Application settings loaded from the environment / .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import load_dotenv


def generate_fernet_key() -> str:
    """Return a fresh Fernet key suitable for CONFIG_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode()


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    admin_chat_ids: tuple[int, ...]
    encryption_key: str
    database_file: Path
    graph_api_version: str
    poll_interval_seconds: int
    initial_sync: str  # "skip" | "send"
    default_language: str  # "en" | "vi"
    fanout_concurrency: int


def _parse_admin_ids(raw: str) -> tuple[int, ...]:
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError as exc:
            raise ValueError(f"ADMIN_CHAT_IDS contains a non-integer value: {part!r}") from exc
    return tuple(ids)


def load_settings(env_file: str | Path | None = None) -> Settings:
    """Load settings from ``.env`` (if present) and the process environment."""
    load_dotenv(dotenv_path=env_file)

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")

    admin_chat_ids = _parse_admin_ids(os.environ.get("ADMIN_CHAT_IDS", ""))
    if not admin_chat_ids:
        raise ValueError("ADMIN_CHAT_IDS is not set (at least one admin chat ID is required)")

    encryption_key = os.environ.get("CONFIG_ENCRYPTION_KEY", "").strip()
    if not encryption_key:
        raise ValueError("CONFIG_ENCRYPTION_KEY is not set")
    try:
        Fernet(encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise ValueError("CONFIG_ENCRYPTION_KEY is not a valid Fernet key") from exc

    database_file = Path(os.environ.get("DATABASE_FILE", "data/bot.db")).expanduser()

    graph_api_version = os.environ.get("GRAPH_API_VERSION", "v26.0").strip() or "v26.0"

    try:
        poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
    except ValueError as exc:
        raise ValueError("POLL_INTERVAL_SECONDS must be an integer") from exc
    poll_interval = max(60, poll_interval)

    initial_sync = os.environ.get("INITIAL_SYNC", "skip").strip().lower()
    if initial_sync not in {"skip", "send"}:
        raise ValueError('INITIAL_SYNC must be "skip" or "send"')

    default_language = os.environ.get("DEFAULT_LANGUAGE", "en").strip().lower()
    if default_language not in {"en", "vi"}:
        raise ValueError('DEFAULT_LANGUAGE must be "en" or "vi"')

    try:
        fanout_concurrency = int(os.environ.get("FANOUT_CONCURRENCY", "10"))
    except ValueError as exc:
        raise ValueError("FANOUT_CONCURRENCY must be an integer") from exc
    fanout_concurrency = max(1, min(30, fanout_concurrency))

    return Settings(
        telegram_bot_token=bot_token,
        admin_chat_ids=admin_chat_ids,
        encryption_key=encryption_key,
        database_file=database_file,
        graph_api_version=graph_api_version,
        poll_interval_seconds=poll_interval,
        initial_sync=initial_sync,
        default_language=default_language,
        fanout_concurrency=fanout_concurrency,
    )
