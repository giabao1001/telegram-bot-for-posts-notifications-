"""Formatting of Facebook posts into Telegram HTML messages."""

from __future__ import annotations

import html
from typing import Any

from .i18n import t

_MAX_MESSAGE_CHARS = 3000


def format_post_notification(
    school_name: str,
    page_name: str,
    post: dict[str, Any],
    language: str = "en",
) -> str:
    """Render a new-post notification in the subscriber's language."""
    raw_message = str(post.get("message") or t(language, "(Photo, video, or post without text)"))
    message = html.escape(raw_message)
    if len(message) > _MAX_MESSAGE_CHARS:
        message = message[: _MAX_MESSAGE_CHARS - 3] + "..."

    created = html.escape(str(post.get("created_time", "")))
    link = str(post.get("permalink_url") or "")

    parts = [
        f"<b>{html.escape(t(language, 'New event post'))} — {html.escape(school_name)}</b>",
        f"{html.escape(page_name)}",
        "",
        message,
    ]
    if created:
        parts.extend(["", f"<i>{created}</i>"])
    if link:
        parts.extend(
            ["", f'<a href="{html.escape(link, quote=True)}">{html.escape(t(language, "Open on Facebook"))}</a>']
        )
    return "\n".join(parts)


def parse_facebook_page_ref(text: str) -> tuple[str, str] | None:
    """Parse a user-supplied Facebook page reference.

    Returns ``("id", numeric_id)`` or ``("username", slug)``, or None when the
    text doesn't look like a Facebook page reference at all.
    """
    cleaned = text.strip().strip("<>").rstrip("/")
    if not cleaned:
        return None
    lowered = cleaned.lower()
    # Strip URL down to the last path segment, e.g.
    # https://www.facebook.com/profile.php?id=123 -> last segment handling below
    if "facebook.com" in lowered or "fb.com" in lowered:
        if "profile.php" in lowered:
            import re

            match = re.search(r"[?&]id=(\d+)", cleaned)
            if match:
                return ("id", match.group(1))
            return None
        segment = cleaned.split("?")[0].rstrip("/").split("/")[-1]
        cleaned = segment
    if cleaned.isdigit():
        return ("id", cleaned)
    import re

    if re.fullmatch(r"[A-Za-z0-9.]{1,50}", cleaned):
        return ("username", cleaned)
    return None
