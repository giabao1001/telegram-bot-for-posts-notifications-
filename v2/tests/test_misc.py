"""Tests for i18n coverage, message formatting, page-ref parsing, and config."""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from diemrenluyen_v2 import i18n
from diemrenluyen_v2.config import load_settings
from diemrenluyen_v2.messages import format_post_notification, parse_facebook_page_ref


def test_every_vietnamese_key_resolves() -> None:
    import string

    formatter = string.Formatter()
    for key, vi_text in i18n.VIETNAMESE.items():
        placeholders = {
            name: f"<{name}>" for _, name, _, _ in formatter.parse(key) if name
        }
        assert i18n.t("en", key, **placeholders) == key.format(**placeholders)
        assert i18n.t("vi", key, **placeholders) == vi_text.format(**placeholders)
        assert vi_text != key  # a translation must actually differ


def test_translation_formatting() -> None:
    assert i18n.t("en", "Subscribed to {name}.", name="Uni") == "Subscribed to Uni."
    assert i18n.t("vi", "Subscribed to {name}.", name="Uni") == "Đã đăng ký theo dõi Uni."


def test_format_post_notification_escapes_and_links() -> None:
    post = {
        "id": "p1",
        "message": "<script>alert('x')</script> Party!",
        "created_time": "2026-10-14",
        "permalink_url": "https://facebook.com/p1",
    }
    text = format_post_notification("Uni", "Events", post, "en")
    assert "<script>" not in text
    assert "&lt;script&gt;" in text
    assert "New event post" in text and "Uni" in text and "Events" in text
    assert "https://facebook.com/p1" in text
    vi_text = format_post_notification("Uni", "Events", post, "vi")
    assert "Bài viết sự kiện mới" in vi_text


def test_format_post_notification_truncates() -> None:
    post = {"id": "p1", "message": "x" * 5000}
    text = format_post_notification("Uni", "Events", post, "en")
    assert text.count("x") <= 3000 and text.rstrip().endswith("...")


def test_parse_facebook_page_ref() -> None:
    assert parse_facebook_page_ref("123456789") == ("id", "123456789")
    assert parse_facebook_page_ref("https://www.facebook.com/123456789/") == ("id", "123456789")
    assert parse_facebook_page_ref("https://facebook.com/profile.php?id=98765") == ("id", "98765")
    assert parse_facebook_page_ref("https://www.facebook.com/some.page") == ("username", "some.page")
    assert parse_facebook_page_ref("not a page!!!") is None
    assert parse_facebook_page_ref("") is None


def _env(monkeypatch, **overrides) -> None:
    base = {
        "TELEGRAM_BOT_TOKEN": "tok",
        "ADMIN_CHAT_IDS": "111, 222",
        "CONFIG_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    for key in ("TELEGRAM_BOT_TOKEN", "ADMIN_CHAT_IDS", "CONFIG_ENCRYPTION_KEY",
                "DATABASE_FILE", "POLL_INTERVAL_SECONDS", "INITIAL_SYNC",
                "DEFAULT_LANGUAGE", "FANOUT_CONCURRENCY", "GRAPH_API_VERSION"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {**base, **overrides}.items():
        monkeypatch.setenv(key, value)


def test_load_settings_ok(monkeypatch) -> None:
    _env(monkeypatch)
    settings = load_settings()
    assert settings.admin_chat_ids == (111, 222)
    assert settings.poll_interval_seconds == 300
    assert settings.initial_sync == "skip"


def test_load_settings_validation(monkeypatch) -> None:
    _env(monkeypatch, TELEGRAM_BOT_TOKEN="")
    with pytest.raises(ValueError):
        load_settings()
    _env(monkeypatch, ADMIN_CHAT_IDS="abc")
    with pytest.raises(ValueError):
        load_settings()
    _env(monkeypatch, CONFIG_ENCRYPTION_KEY="not-a-key")
    with pytest.raises(ValueError):
        load_settings()
    _env(monkeypatch, INITIAL_SYNC="sometimes")
    with pytest.raises(ValueError):
        load_settings()
