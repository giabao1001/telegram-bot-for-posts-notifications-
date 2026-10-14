"""Entrypoint: run the Telegram bot plus the Facebook polling loop.

The bot handles subscriptions in real time; a background asyncio task polls
the approved Facebook pages every POLL_INTERVAL_SECONDS (the synchronous
engine runs in a worker thread so it never blocks Telegram updates) and fans
new posts out to each school's subscribers in their own language.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from telegram import Update
from telegram.error import Forbidden, TelegramError
from telegram.ext import Application

from . import engine
from .admin import register_admin_handlers
from .bot import register_user_handlers
from .config import Settings, load_settings
from .crypto import TokenCipher
from .db import Database
from .engine import Delivery

LOG = logging.getLogger("diemrenluyen")


async def deliver_all(
    app: Application, database: Database, deliveries: list[Delivery], settings: Settings
) -> None:
    """Send deliveries, chunked for Telegram rate limits."""
    semaphore = asyncio.Semaphore(settings.fanout_concurrency)

    async def _send(delivery: Delivery) -> None:
        async with semaphore:
            try:
                await app.bot.send_message(
                    chat_id=delivery.chat_id,
                    text=delivery.text,
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
            except Forbidden:
                # User blocked the bot — stop trying until they /start again.
                database.set_user_active(delivery.chat_id, False)
                LOG.info("User %s blocked the bot; marked inactive", delivery.chat_id)
            except TelegramError as exc:
                LOG.warning("Could not deliver to %s: %s", delivery.chat_id, exc)
            # Gentle pacing between messages.
            await asyncio.sleep(0.05)

    for i in range(0, len(deliveries), 50):
        chunk = deliveries[i : i + 50]
        await asyncio.gather(*(_send(d) for d in chunk))


async def poll_loop(app: Application) -> None:
    database: Database = app.bot_data["db"]
    cipher: TokenCipher = app.bot_data["cipher"]
    settings: Settings = app.bot_data["settings"]
    LOG.info(
        "Poll loop started: every %ss, initial_sync=%s",
        settings.poll_interval_seconds,
        settings.initial_sync,
    )
    while True:
        try:
            result, new_posts = await asyncio.to_thread(
                engine.poll_once, database, cipher, settings
            )
            LOG.info("Poll cycle: %s", engine.describe_result(result))
            if new_posts:
                deliveries = engine.plan_deliveries(database, new_posts)
                LOG.info(
                    "Fanning out %d new posts to %d deliveries",
                    len(new_posts),
                    len(deliveries),
                )
                await deliver_all(app, database, deliveries, settings)
        except Exception:
            LOG.exception("Poll loop iteration failed")
        await asyncio.sleep(settings.poll_interval_seconds)


async def post_init(app: Application) -> None:
    app.create_task(poll_loop(app), name="facebook-poll-loop")


def build_application(settings: Settings) -> Application:
    database = Database(settings.database_file)
    cipher = TokenCipher(settings.encryption_key)
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .build()
    )
    app.bot_data["db"] = database
    app.bot_data["settings"] = settings
    app.bot_data["cipher"] = cipher
    register_admin_handlers(app)
    register_user_handlers(app, settings, database)
    return app


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
    )
    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1
    app = build_application(settings)
    LOG.info("Starting DiemRenLuyen v2 bot…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
