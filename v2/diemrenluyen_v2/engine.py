"""Polling engine: read approved Facebook pages, dedupe, plan fan-out deliveries.

The engine is synchronous and side-effect-light on purpose so it is easy to
unit-test: ``poll_once`` returns the new posts, and ``plan_deliveries`` turns
them into per-user ``Delivery`` objects (with each subscriber's language).
The Telegram sending itself lives in ``main.py`` / ``bot.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from . import db as db_module
from .config import Settings
from .crypto import TokenCipher
from .db import Database
from .i18n import t
from .messages import format_post_notification
from .meta import MetaClient, MetaError


LOG = logging.getLogger("diemrenluyen.engine")


@dataclass(frozen=True)
class NewPost:
    page_id: int
    school_id: int
    school_name: str
    page_name: str
    post: dict[str, Any]


@dataclass(frozen=True)
class Delivery:
    chat_id: int
    language: str
    text: str


@dataclass
class PollResult:
    pages_checked: int = 0
    new_posts: int = 0
    skipped_on_first_sync: int = 0
    errors: list[str] = field(default_factory=list)
    auto_disabled: list[str] = field(default_factory=list)


MetaFactory = Callable[[str], MetaClient]


def poll_once(
    database: Database,
    cipher: TokenCipher,
    settings: Settings,
    meta_factory: MetaFactory = MetaClient,
) -> tuple[PollResult, list[NewPost]]:
    """Poll every approved page once. Returns (result, new posts)."""
    result = PollResult()
    new_posts: list[NewPost] = []

    for page in database.list_approved_pages():
        token = cipher.decrypt(database.get_page_token_encrypted(page.id))
        if not token:
            database.record_page_failure(page.id, "No access token stored for this page")
            result.errors.append(f"Page {page.page_name}: no access token stored")
            continue

        client = meta_factory(settings.graph_api_version)
        first_sync = not database.is_page_initialized(page.id)
        try:
            page_name = client.get_page_name(page.fb_page_id, token)
            posts = client.get_recent_posts(page.fb_page_id, token)
        except MetaError as exc:
            disabled = database.record_page_failure(page.id, str(exc))
            LOG.warning("Could not read Facebook page %s (%s): %s", page.page_name, page.fb_page_id, exc)
            result.errors.append(f"Page {page.page_name}: {exc}")
            if disabled:
                result.auto_disabled.append(page.page_name)
                LOG.error(
                    "Page %s auto-disabled after %d consecutive failures",
                    page.page_name,
                    db_module.MAX_CONSECUTIVE_FAILURES,
                )
            continue
        except Exception as exc:  # defensive: never let one page kill the cycle
            LOG.exception("Unexpected error reading page %s", page.page_name)
            result.errors.append(f"Page {page.page_name}: {exc}")
            continue

        result.pages_checked += 1
        database.record_page_success(page.id)
        if page_name != page.page_name:
            database.update_page_name(page.id, page_name)

        # Graph returns newest first; reverse so notifications arrive chronologically.
        for post in reversed(posts):
            post_id = str(post.get("id", ""))
            if not post_id or database.has_seen(page.id, post_id):
                continue
            if first_sync and settings.initial_sync == "skip":
                database.mark_seen(page.id, post_id)
                result.skipped_on_first_sync += 1
                continue
            database.mark_seen(page.id, post_id)
            new_posts.append(
                NewPost(
                    page_id=page.id,
                    school_id=page.school_id,
                    school_name=page.school_name,
                    page_name=page_name,
                    post=post,
                )
            )
            result.new_posts += 1

        database.mark_page_initialized(page.id)
        if first_sync and settings.initial_sync == "skip":
            LOG.info(
                "Initial sync for page %s: existing posts recorded without alerts",
                page.page_name,
            )

    return result, new_posts


def plan_deliveries(database: Database, new_posts: list[NewPost]) -> list[Delivery]:
    """Fan out new posts to active subscribers of each post's school."""
    deliveries: list[Delivery] = []
    for item in new_posts:
        for sub in database.subscribers_for_school(item.school_id):
            text = format_post_notification(
                item.school_name, item.page_name, item.post, sub.language
            )
            deliveries.append(Delivery(chat_id=sub.chat_id, language=sub.language, text=text))
    return deliveries


def describe_result(result: PollResult, language: str = "en") -> str:
    parts = [
        f"pages checked: {result.pages_checked}",
        f"new posts: {result.new_posts}",
    ]
    if result.skipped_on_first_sync:
        parts.append(f"skipped on first sync: {result.skipped_on_first_sync}")
    if result.errors:
        parts.append(f"errors: {len(result.errors)}")
    return ", ".join(parts)
