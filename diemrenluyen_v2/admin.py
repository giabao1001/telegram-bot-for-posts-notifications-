"""Admin-only commands: moderation queue, school/page management, broadcast.

Admins are the Telegram chat IDs listed in ``ADMIN_CHAT_IDS``. Every handler
here refuses non-admins first.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Awaitable, Callable

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .config import Settings
from .crypto import TokenCipher
from .db import STATUS_APPROVED, STATUS_DISABLED, STATUS_PENDING, STATUS_REJECTED, Database
from .i18n import t
from .messages import parse_facebook_page_ref
from .meta import MetaClient, MetaError

LOG = logging.getLogger("diemrenluyen.admin")

# Conversation state for /approvepage (waiting for the Page access token)
WAITING_TOKEN = 0

Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[Any]]


def admin_only(handler: Handler) -> Handler:
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Any:
        settings: Settings = context.bot_data["settings"]
        user = update.effective_user
        lang = "en"
        database: Database = context.bot_data["db"]
        if user is not None:
            record = database.get_user(user.id)
            if record is not None:
                lang = record.language
        if user is None or user.id not in settings.admin_chat_ids:
            message = update.effective_message
            if message is not None:
                await message.reply_text(t(lang, "Admin only."))
            return None
        return await handler(update, context)

    return wrapper


def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings: Settings = context.bot_data["settings"]
    user = update.effective_user
    return user is not None and user.id in settings.admin_chat_ids


@admin_only
async def pendingpages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database: Database = context.bot_data["db"]
    pages = database.list_pages(status=STATUS_PENDING)
    message = update.effective_message
    assert message is not None
    if not pages:
        await message.reply_text(t("en", "No pending suggestions."))
        return
    lines = [t("en", "Pending page suggestions:")]
    for page in pages:
        who = page.added_by_chat_id if page.added_by_chat_id else "?"
        lines.append(
            f"\n#{page.id} — {page.page_name} (FB id {page.fb_page_id})\n"
            f"School: {page.school_name}\n"
            f"{t('en', 'Suggested by {user}', user=who)}"
            + (f"\n{t('en', 'Note: {note}', note=page.note)}" if page.note else "")
        )
    lines.append("\nUse /approvepage <id> or /rejectpage <id>")
    await message.reply_text("\n".join(lines))


@admin_only
async def approvepage_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    assert message is not None
    if not context.args:
        await message.reply_text(t("en", "Usage: /approvepage <id>"))
        return ConversationHandler.END
    try:
        page_id = int(context.args[0])
    except ValueError:
        await message.reply_text(t("en", "Usage: /approvepage <id>"))
        return ConversationHandler.END
    database: Database = context.bot_data["db"]
    page = database.get_page(page_id)
    if page is None or page.status != STATUS_PENDING:
        await message.reply_text(t("en", "No pending page with ID {id}.", id=page_id))
        return ConversationHandler.END
    context.user_data["approve_page_id"] = page_id
    await message.reply_text(
        t("en", "Now send me the Facebook Page access token for {name}. (Tip: delete your token message afterwards.)",
          name=page.page_name)
    )
    return WAITING_TOKEN


@admin_only
async def approvepage_got_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    database: Database = context.bot_data["db"]
    settings: Settings = context.bot_data["settings"]
    cipher: TokenCipher = context.bot_data["cipher"]
    message = update.effective_message
    assert message is not None
    page_id = context.user_data.pop("approve_page_id", None)
    token = (message.text or "").strip()
    if page_id is None or not token:
        await message.reply_text(t("en", "Cancelled."))
        return ConversationHandler.END
    page = database.get_page(page_id)
    if page is None:
        await message.reply_text(t("en", "No page with ID {id}.", id=page_id))
        return ConversationHandler.END
    # Verify the token against Meta before storing anything.
    try:
        page_name = MetaClient(settings.graph_api_version).get_page_name(page.fb_page_id, token)
    except MetaError as exc:
        await message.reply_text(t("en", "Meta could not verify this page/token: {error}", error=exc))
        return ConversationHandler.END
    database.approve_page(page_id, cipher.encrypt(token), page_name)
    await message.reply_text(t("en", "Page {name} approved and is now being watched.", name=page_name))
    # Tell the submitter their page went live.
    if page.added_by_chat_id:
        try:
            await context.bot.send_message(
                chat_id=page.added_by_chat_id,
                text=f"✅ {page_name}: {t('en', 'approved')}",
            )
        except Exception:
            LOG.warning("Could not notify submitter %s", page.added_by_chat_id)
    return ConversationHandler.END


@admin_only
async def rejectpage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    assert message is not None
    if not context.args:
        await message.reply_text(t("en", "Usage: /rejectpage <id>"))
        return
    try:
        page_id = int(context.args[0])
    except ValueError:
        await message.reply_text(t("en", "Usage: /rejectpage <id>"))
        return
    database: Database = context.bot_data["db"]
    page = database.get_page(page_id)
    if page is None:
        await message.reply_text(t("en", "No page with ID {id}.", id=page_id))
        return
    database.set_page_status(page_id, STATUS_REJECTED)
    await message.reply_text(t("en", "Page suggestion {id} rejected.", id=page_id))
    if page.added_by_chat_id:
        try:
            await context.bot.send_message(
                chat_id=page.added_by_chat_id,
                text=f"❌ {page.page_name}: {t('en', 'rejected')}",
            )
        except Exception:
            LOG.warning("Could not notify submitter %s", page.added_by_chat_id)


@admin_only
async def addschool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    assert message is not None
    if not context.args:
        await message.reply_text(t("en", "Usage: /addschool <name>"))
        return
    database: Database = context.bot_data["db"]
    name = " ".join(context.args)
    try:
        school = database.add_school(name)
    except ValueError:
        await message.reply_text(t("en", "That school already exists."))
        return
    await message.reply_text(t("en", "School {name} added with ID {id}.", name=school.name, id=school.id))


@admin_only
async def addpageadmin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Directly add an approved page: /addpageadmin <school_id> <fb_page> <token> [name]."""
    message = update.effective_message
    assert message is not None
    if len(context.args or []) < 3:
        await message.reply_text(t("en", "Usage: /addpageadmin <school_id> <fb_page_id_or_link> <token> [page name]"))
        return
    database: Database = context.bot_data["db"]
    settings: Settings = context.bot_data["settings"]
    cipher: TokenCipher = context.bot_data["cipher"]
    try:
        school_id = int(context.args[0])
    except ValueError:
        await message.reply_text(t("en", "Usage: /addpageadmin <school_id> <fb_page_id_or_link> <token> [page name]"))
        return
    school = database.get_school(school_id)
    if school is None:
        await message.reply_text(t("en", "No page with ID {id}.", id=school_id))
        return
    parsed = parse_facebook_page_ref(context.args[1])
    if parsed is None or parsed[0] != "id":
        await message.reply_text(
            t("en", "I couldn't understand that as a Facebook page. Send a facebook.com link or a numeric Page ID.")
        )
        return
    token = context.args[2]
    custom_name = " ".join(context.args[3:]) if len(context.args) > 3 else ""
    try:
        page_name = MetaClient(settings.graph_api_version).get_page_name(parsed[1], token)
    except MetaError as exc:
        await message.reply_text(t("en", "Meta could not verify this page/token: {error}", error=exc))
        return
    try:
        page = database.add_page_submission(
            school_id=school.id,
            fb_page_id=parsed[1],
            page_name=custom_name or page_name,
            added_by_chat_id=(update.effective_user.id if update.effective_user else None),
            token_encrypted=cipher.encrypt(token),
            status=STATUS_APPROVED,
        )
    except ValueError as exc:
        await message.reply_text(str(exc))
        return
    await message.reply_text(
        t("en", "Page {name} approved and is now being watched.", name=page.page_name)
    )


@admin_only
async def listschools(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database: Database = context.bot_data["db"]
    schools = database.list_schools()
    message = update.effective_message
    assert message is not None
    if not schools:
        await message.reply_text(t("en", "No schools yet."))
        return
    lines = [t("en", "Schools:")] + [f"• #{s.id} {s.name}" for s in schools]
    await message.reply_text("\n".join(lines))


@admin_only
async def listpages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database: Database = context.bot_data["db"]
    message = update.effective_message
    assert message is not None
    school_id = None
    if context.args:
        try:
            school_id = int(context.args[0])
        except ValueError:
            pass
    pages = database.list_pages(school_id=school_id)
    if not pages:
        await message.reply_text(t("en", "No pages yet."))
        return
    lines = [t("en", "Pages:")]
    for page in pages:
        flag = f" ⚠️ {page.last_error[:60]}" if page.last_error else ""
        lines.append(
            f"• #{page.id} {page.page_name} [{page.status}] — {page.school_name}{flag}"
        )
    await message.reply_text("\n".join(lines))


@admin_only
async def disablepage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    assert message is not None
    if not context.args:
        await message.reply_text(t("en", "Usage: /disablepage <id>"))
        return
    database: Database = context.bot_data["db"]
    try:
        page_id = int(context.args[0])
    except ValueError:
        await message.reply_text(t("en", "Usage: /disablepage <id>"))
        return
    if database.get_page(page_id) is None:
        await message.reply_text(t("en", "No page with ID {id}.", id=page_id))
        return
    database.set_page_status(page_id, STATUS_DISABLED)
    await message.reply_text(t("en", "Page {id} disabled — it will no longer be polled.", id=page_id))


@admin_only
async def enablepage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    assert message is not None
    if not context.args:
        await message.reply_text(t("en", "Usage: /enablepage <id>"))
        return
    database: Database = context.bot_data["db"]
    try:
        page_id = int(context.args[0])
    except ValueError:
        await message.reply_text(t("en", "Usage: /enablepage <id>"))
        return
    page = database.get_page(page_id)
    if page is None:
        await message.reply_text(t("en", "No page with ID {id}.", id=page_id))
        return
    if not database.get_page_token_encrypted(page_id):
        await message.reply_text(
            t("en", "Meta could not verify this page/token: {error}", error="no token stored")
        )
        return
    database.set_page_status(page_id, STATUS_APPROVED)
    await message.reply_text(t("en", "Page {id} re-enabled.", id=page_id))


@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    assert message is not None
    text = " ".join(context.args or [])
    if not text:
        await message.reply_text(t("en", "Usage: /broadcast <message>"))
        return
    database: Database = context.bot_data["db"]
    sent = 0
    for chat_id in database.active_chat_ids():
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
            sent += 1
        except Exception:
            LOG.warning("Broadcast to %s failed", chat_id)
    await message.reply_text(t("en", "Broadcast sent to {n} subscriber(s).", n=sent))


@admin_only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    database: Database = context.bot_data["db"]
    message = update.effective_message
    assert message is not None
    lines = [
        t("en", "Bot stats:"),
        t("en", "users: {n}", n=database.count_users()),
        t("en", "active users: {n}", n=database.count_users(active_only=True)),
        t("en", "schools: {n}", n=len(database.list_schools())),
        t("en", "pages (approved): {n}", n=len(database.list_pages(status=STATUS_APPROVED))),
        t("en", "pages (pending): {n}", n=len(database.list_pages(status=STATUS_PENDING))),
        t("en", "subscriptions: {n}", n=database.count_subscriptions()),
    ]
    await message.reply_text("\n".join(lines))


async def approvepage_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("approve_page_id", None)
    message = update.effective_message
    assert message is not None
    await message.reply_text(t("en", "Cancelled."))
    return ConversationHandler.END


def build_approve_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("approvepage", approvepage_start)],
        states={
            WAITING_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, approvepage_got_token)
            ],
        },
        fallbacks=[CommandHandler("cancel", approvepage_cancel)],
        per_message=False,
    )


def register_admin_handlers(app: Application) -> None:
    # NOTE: admin_only is enforced inside each handler (not via filters) so the
    # ConversationHandler entry points stay simple.
    app.add_handler(build_approve_conversation())
    app.add_handler(CommandHandler("pendingpages", pendingpages))
    app.add_handler(CommandHandler("rejectpage", rejectpage))
    app.add_handler(CommandHandler("addschool", addschool))
    app.add_handler(CommandHandler("addpageadmin", addpageadmin))
    app.add_handler(CommandHandler("listschools", listschools))
    app.add_handler(CommandHandler("listpages", listpages))
    app.add_handler(CommandHandler("disablepage", disablepage))
    app.add_handler(CommandHandler("enablepage", enablepage))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("stats", stats))
