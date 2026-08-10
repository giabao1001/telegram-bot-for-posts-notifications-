from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app import Config, FacebookPage


@dataclass(frozen=True)
class StoredPage:
    page_id: str
    label: str
    created_at: str


class DashboardStore:
    def __init__(self, database_path: Path, encryption_key: str) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.cipher = Fernet(encryption_key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError("CONFIG_ENCRYPTION_KEY is not a valid Fernet key") from exc
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_pages (
                    page_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    access_token_encrypted TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_posts (
                    post_id TEXT PRIMARY KEY,
                    seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS initialized_pages (
                    page_id TEXT PRIMARY KEY,
                    initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_log_created_at "
                "ON activity_log(created_at DESC)"
            )
            defaults = {
                "telegram_bot_token": "",
                "telegram_chat_id": "",
                "graph_api_version": "v26.0",
                "poll_interval_seconds": "300",
                "initial_sync": "skip",
                "enabled": "1",
                "last_check": "Never",
                "last_result": "Waiting for the first check",
            }
            connection.executemany(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                defaults.items(),
            )
            connection.execute("PRAGMA optimize")

    def get_setting(self, key: str, default: str = "") -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else default

    def get_settings(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        values = {str(row["key"]): str(row["value"]) for row in rows}
        token = self._decrypt(values.get("telegram_bot_token", ""))
        values["telegram_configured"] = "1" if token else "0"
        values["telegram_bot_token"] = token
        return values

    def save_settings(
        self,
        *,
        telegram_bot_token: str | None,
        telegram_chat_id: str,
        graph_api_version: str,
        poll_interval_seconds: int,
        initial_sync: str,
    ) -> None:
        values = {
            "telegram_chat_id": telegram_chat_id.strip(),
            "graph_api_version": graph_api_version.strip(),
            "poll_interval_seconds": str(max(30, poll_interval_seconds)),
            "initial_sync": initial_sync,
        }
        if telegram_bot_token:
            values["telegram_bot_token"] = self._encrypt(telegram_bot_token.strip())
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                values.items(),
            )

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def list_pages(self) -> list[StoredPage]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT page_id, label, created_at FROM dashboard_pages ORDER BY label"
            ).fetchall()
        return [StoredPage(str(r["page_id"]), str(r["label"]), str(r["created_at"])) for r in rows]

    def add_page(self, page_id: str, label: str, access_token: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dashboard_pages(page_id, label, access_token_encrypted)
                VALUES (?, ?, ?)
                ON CONFLICT(page_id) DO UPDATE SET
                    label = excluded.label,
                    access_token_encrypted = excluded.access_token_encrypted
                """,
                (page_id.strip(), label.strip(), self._encrypt(access_token.strip())),
            )

    def remove_page(self, page_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM dashboard_pages WHERE page_id = ?", (page_id,))
            connection.execute("DELETE FROM initialized_pages WHERE page_id = ?", (page_id,))
            connection.execute(
                "DELETE FROM seen_posts WHERE post_id LIKE ?", (f"{page_id}_%",)
            )

    def build_config(self) -> Config:
        settings = self.get_settings()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT page_id, access_token_encrypted FROM dashboard_pages ORDER BY page_id"
            ).fetchall()
        pages = tuple(
            FacebookPage(str(row["page_id"]), self._decrypt(str(row["access_token_encrypted"])))
            for row in rows
        )
        return Config(
            telegram_bot_token=settings["telegram_bot_token"],
            telegram_chat_id=settings.get("telegram_chat_id", ""),
            pages=pages,
            graph_api_version=settings.get("graph_api_version", "v26.0"),
            poll_interval_seconds=max(30, int(settings.get("poll_interval_seconds", "300"))),
            initial_sync=settings.get("initial_sync", "skip"),
            database_path=self.database_path,
        )

    def log(self, level: str, message: str) -> None:
        safe_level = level if level in {"success", "info", "warning", "error"} else "info"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO activity_log(level, message) VALUES (?, ?)",
                (safe_level, message[:1000]),
            )
            connection.execute(
                "DELETE FROM activity_log WHERE id NOT IN "
                "(SELECT id FROM activity_log ORDER BY id DESC LIMIT 200)"
            )

    def recent_activity(self, limit: int = 12) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT level, message, created_at FROM activity_log "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_check_status(self, result: str) -> None:
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.set_setting("last_check", now)
        self.set_setting("last_result", result)

    def _encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self.cipher.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError(
                "Stored credentials cannot be decrypted. Restore the original CONFIG_ENCRYPTION_KEY."
            ) from exc
