"""Shared fixtures for the test-suite."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from diemrenluyen_v2.config import Settings
from diemrenluyen_v2.crypto import TokenCipher
from diemrenluyen_v2.db import Database


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


@pytest.fixture()
def cipher() -> TokenCipher:
    return TokenCipher(Fernet.generate_key().decode())


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        telegram_bot_token="test-token",
        admin_chat_ids=(111,),
        encryption_key=Fernet.generate_key().decode(),
        database_file=Path("data/bot.db"),
        graph_api_version="v26.0",
        poll_interval_seconds=300,
        initial_sync="send",
        default_language="en",
        fanout_concurrency=10,
    )
