from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

import app
from storage import DashboardStore
from translations import translate


def test_format_post_escapes_html() -> None:
    text = app.format_post(
        "Cats & Dogs",
        {
            "message": "<b>not markup</b>",
            "created_time": "2026-01-01",
            "permalink_url": "https://example.test/post?a=1&b=2",
        },
    )
    assert "Cats &amp; Dogs" in text
    assert "&lt;b&gt;not markup&lt;/b&gt;" in text
    assert 'a=1&amp;b=2' in text


def test_first_sync_and_deduplication(tmp_path: Path, monkeypatch) -> None:
    delivered: list[str] = []
    posts = [{"id": "page_1", "message": "existing"}]

    class FakeMeta:
        def __init__(self, version: str) -> None:
            pass

        def get_page_name(self, page: app.FacebookPage) -> str:
            return "Test Page"

        def get_recent_posts(self, page: app.FacebookPage):
            return list(posts)

    class FakeTelegram:
        def __init__(self, token: str, chat_id: str) -> None:
            pass

        def send(self, text: str) -> None:
            delivered.append(text)

    monkeypatch.setattr(app, "MetaClient", FakeMeta)
    monkeypatch.setattr(app, "TelegramClient", FakeTelegram)
    config = app.Config(
        "bot", "chat", (app.FacebookPage("page", "meta"),),
        "v26.0", 300, "skip", tmp_path / "notifier.db"
    )
    store = app.SeenPostStore(config.database_path)
    assert app.poll_once_detailed(config, store).sent == 0
    posts.append({"id": "page_2", "message": "new"})
    assert app.poll_once_detailed(config, store).sent == 1
    assert app.poll_once_detailed(config, store).sent == 0
    assert len(delivered) == 1


def test_dashboard_store_encrypts_credentials(tmp_path: Path) -> None:
    database = tmp_path / "dashboard.db"
    store = DashboardStore(database, Fernet.generate_key().decode())
    store.save_settings(
        telegram_bot_token="secret-bot-token",
        telegram_chat_id="123",
        graph_api_version="v26.0",
        poll_interval_seconds=300,
        initial_sync="skip",
    )
    store.add_page("42", "A Page", "secret-page-token")
    assert b"secret-bot-token" not in database.read_bytes()
    assert b"secret-page-token" not in database.read_bytes()
    config = store.build_config()
    assert config.telegram_bot_token == "secret-bot-token"
    assert config.pages[0].access_token == "secret-page-token"


def test_vietnamese_translation_and_formatting() -> None:
    assert translate("vi", "Connect Telegram") == "Kết nối Telegram"
    assert (
        translate("vi", "Stop watching {name}?", name="Trang thử")
        == "Ngừng theo dõi Trang thử?"
    )
    assert translate("en", "Save settings") == "Save settings"
