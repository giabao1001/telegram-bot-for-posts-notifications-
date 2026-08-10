from __future__ import annotations

import html
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


LOG = logging.getLogger("facebook_telegram_notifier")


@dataclass(frozen=True)
class FacebookPage:
    page_id: str
    access_token: str


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_chat_id: str
    pages: tuple[FacebookPage, ...]
    graph_api_version: str
    poll_interval_seconds: int
    initial_sync: str
    database_path: Path

@dataclass(frozen=True)
class PollResult:
    sent: int = 0
    skipped: int = 0
    pages_checked: int = 0
    errors: tuple[str, ...] = ()


class SeenPostStore:
    def __init__(self, path: Path) -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_posts (
                post_id TEXT PRIMARY KEY,
                seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS initialized_pages (
                page_id TEXT PRIMARY KEY,
                initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.connection.commit()

    def has_seen(self, post_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM seen_posts WHERE post_id = ?", (post_id,)
        ).fetchone()
        return row is not None

    def mark_seen(self, post_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO seen_posts(post_id) VALUES (?)", (post_id,)
        )
        self.connection.commit()

    def is_page_initialized(self, page_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM initialized_pages WHERE page_id = ?", (page_id,)
        ).fetchone()
        return row is not None

    def mark_page_initialized(self, page_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO initialized_pages(page_id) VALUES (?)", (page_id,)
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()


class MetaClient:
    def __init__(self, api_version: str) -> None:
        self.base_url = f"https://graph.facebook.com/{api_version}"
        self.session = requests.Session()

    def get_page_name(self, page: FacebookPage) -> str:
        data = self._get(
            f"{self.base_url}/{page.page_id}",
            params={"fields": "name", "access_token": page.access_token},
        )
        return str(data.get("name", page.page_id))

    def get_recent_posts(self, page: FacebookPage) -> list[dict[str, Any]]:
        data = self._get(
            f"{self.base_url}/{page.page_id}/posts",
            params={
                "fields": "id,message,created_time,permalink_url,full_picture",
                "limit": 25,
                "access_token": page.access_token,
            },
        )
        posts = data.get("data", [])
        if not isinstance(posts, list):
            raise RuntimeError("Meta returned an unexpected posts response")
        return posts

    def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.get(url, params=params, timeout=30)
        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise RuntimeError(f"Meta returned HTTP {response.status_code}") from exc
        if not response.ok or "error" in payload:
            error = payload.get("error", {})
            message = error.get("message", f"HTTP {response.status_code}")
            raise RuntimeError(f"Meta API error: {message}")
        return payload


class TelegramClient:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.chat_id = chat_id
        self.session = requests.Session()

    def send(self, text: str) -> None:
        response = self.session.post(
            self.url,
            json={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=30,
        )
        try:
            payload = response.json()
        except requests.JSONDecodeError as exc:
            raise RuntimeError(f"Telegram returned HTTP {response.status_code}") from exc
        if not response.ok or not payload.get("ok"):
            raise RuntimeError(
                f"Telegram API error: {payload.get('description', response.status_code)}"
            )


def format_post(page_name: str, post: dict[str, Any]) -> str:
    raw_message = str(post.get("message") or "(Photo, video, or post without text)")
    message = html.escape(raw_message)
    if len(message) > 3000:
        message = message[:2997] + "..."

    created = html.escape(str(post.get("created_time", "")))
    link = str(post.get("permalink_url") or "")
    safe_name = html.escape(page_name)

    parts = [f"<b>New Facebook post — {safe_name}</b>", "", message]
    if created:
        parts.extend(["", f"<i>{created}</i>"])
    if link:
        parts.extend(["", f'<a href="{html.escape(link, quote=True)}">Open on Facebook</a>'])
    return "\n".join(parts)


def poll_once_detailed(config: Config, store: SeenPostStore) -> PollResult:
    meta = MetaClient(config.graph_api_version)
    telegram = TelegramClient(config.telegram_bot_token, config.telegram_chat_id)
    sent = 0
    skipped = 0
    pages_checked = 0
    errors: list[str] = []

    for page in config.pages:
        first_sync = not store.is_page_initialized(page.page_id)
        try:
            page_name = meta.get_page_name(page)
            posts = meta.get_recent_posts(page)
        except Exception as exc:
            LOG.exception("Could not read Facebook Page %s", page.page_id)
            errors.append(f"Page {page.page_id}: {exc}")
            continue
        pages_checked += 1

        # Graph returns newest first; reverse it so alerts arrive chronologically.
        for post in reversed(posts):
            post_id = str(post.get("id", ""))
            if not post_id or store.has_seen(post_id):
                continue
            if first_sync and config.initial_sync == "skip":
                store.mark_seen(post_id)
                skipped += 1
                continue
            try:
                telegram.send(format_post(page_name, post))
            except Exception as exc:
                LOG.exception("Could not notify Telegram about post %s", post_id)
                errors.append(f"Post {post_id}: {exc}")
                continue
            store.mark_seen(post_id)
            sent += 1
            LOG.info("Sent notification for %s", post_id)

        store.mark_page_initialized(page.page_id)
        if first_sync and config.initial_sync == "skip":
            LOG.info(
                "Initial sync complete for Page %s; existing posts were recorded without alerts",
                page.page_id,
            )
    return PollResult(
        sent=sent,
        skipped=skipped,
        pages_checked=pages_checked,
        errors=tuple(errors),
    )


def poll_once(config: Config, store: SeenPostStore) -> int:
    return poll_once_detailed(config, store).sent

