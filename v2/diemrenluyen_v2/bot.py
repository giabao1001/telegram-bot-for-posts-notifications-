"""Telegram bot: user-facing commands and onboarding flows.

Uses python-telegram-bot (asyncio). All user-visible strings go through
:mod:`diemrenluyen_v2.i18n` so every subscriber gets their own language.
"""

from __future__ import annotations

import logging
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from .db import Database, School
from .i18n import t
from .messages import parse_facebook_page_ref

LOG = logging.getLogger("diemrenluyen.bot")

# Conversation states for /addpage
WAITING_PAGE, WAITING_NOTE = range(2)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.bot_data["db"]  # type: ignore[no-any-return]


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data["settings"]  # type: ignore[no-any-return]


def _lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    database = _db(context)
    user = update.effective_user
    if user is None:
        return _settings(context).default_language
    record = database.get_user(user.id)
    if record is None:
        return _settings(context).default_language
    return record.language


def _ensure_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user is not None:
        _db(context).upsert_user(user.id, _settings(context).default_language)


def _language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
                InlineKeyboardButton("🇻🇳 Tiếng Việt", callback_data="lang:vi"),
            ]
        ]
    )


def _school_keyboard(schools: list[School], selected: set[int], lang: str) -> InlineKeyboardMarkup:
    rows = []
    for school in schools:
        mark = "✅ " if school.id in selected else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{mark}{school.name}", callback_data=f"school:toggle:{school.id}"
                )
            ]
        )
    rows.append([InlineKeyboardButton(f"✔️ {t(lang, 'Done')}", callback_data="school:done")])
    return InlineKeyboardMarkup(rows)


async def _show_school_picker(
    update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str, intro: bool = False
) -> None:
    database = _db(context)
    schools = database.list_schools()
    message = update.effective_message
    assert message is not None
    if not schools:
        await message.reply_text(t(lang, "No schools are available yet. An admin needs to add schools first — please check back later."))
        return
    user = update.effective_user
    selected = (
        {s.id for s in database.user_subscriptions(user.id)} if user else set()
    )
    context.user_data["school_pick"] = selected
    text = t(lang, "Which school(s) do you want to follow? Tap to select, then press Done.")
    if intro:
        text = f"{t(lang, 'Welcome to DiemRenLuyen Bot!')}\n\n{t(lang, 'I notify you about school events posted on Facebook, so you never miss events that count toward your training points (điểm rèn luyện).')}\n\n{text}"
    await message.reply_text(text, reply_markup=_school_keyboard(schools, selected, lang))


# ---------------------------------------------------------------------------
# /start and onboarding
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ensure_user(update, context)
    message = update.effective_message
    assert message is not None
    await message.reply_text(
        f"{t('en', 'Welcome to DiemRenLuyen Bot!')}\n\n{t('en', 'Choose your language:')}",
        reply_markup=_language_keyboard(),
    )


async def language_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None
    await query.answer()
    lang = query.data.split(":", 1)[1] if query.data else "en"
    if lang not in ("en", "vi"):
        lang = "en"
    user = update.effective_user
    assert user is not None
    database = _db(context)
    database.upsert_user(user.id, lang)
    database.set_language(user.id, lang)
    context.user_data["onboarding"] = True
    await query.edit_message_text(t(lang, "Language set to English.") if lang == "en" else t(lang, "Language set to Vietnamese."))
    # Continue straight into the school picker.
    fake_update = update  # reuse for helper
    await _show_school_picker(fake_update, context, lang)


async def school_toggled(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None
    await query.answer()
    try:
        school_id = int((query.data or "").split(":")[-1])
    except ValueError:
        return
    selected: set[int] = context.user_data.get("school_pick", set())
    if school_id in selected:
        selected.discard(school_id)
    else:
        selected.add(school_id)
    context.user_data["school_pick"] = selected
    lang = _lang(update, context)
    schools = _db(context).list_schools()
    # Keep only IDs that still exist.
    valid = {s.id for s in schools}
    selected.intersection_update(valid)
    await query.edit_message_reply_markup(
        reply_markup=_school_keyboard(schools, selected, lang)
    )


async def school_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    assert query is not None
    await query.answer()
    database = _db(context)
    user = update.effective_user
    assert user is not None
    lang = _lang(update, context)
    selected: set[int] = context.user_data.get("school_pick", set())
    valid_ids = {s.id for s in database.list_schools()}
    selected = {sid for sid in selected if sid in valid_ids}
    database.set_subscriptions(user.id, sorted(selected))
    context.user_data.pop("school_pick", None)
    context.user_data.pop("onboarding", None)
    names = [s.name for s in database.user_subscriptions(user.id)]
    if names:
        text = (
            f"{t(lang, 'You\'re subscribed to:')}\n"
            + "\n".join(f"• {n}" for n in names)
            + f"\n\n{t(lang, 'You\'ll receive new event posts from these schools\' Facebook pages.')}"
        )
    else:
        text = t(lang, "You're not subscribed to any school yet. Use /schools to pick your schools.")
    await query.edit_message_text(text)


# ---------------------------------------------------------------------------
# subscription commands
# ---------------------------------------------------------------------------

async def schools_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ensure_user(update, context)
    await _show_school_picker(update, context, _lang(update, context))


async def language_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ensure_user(update, context)
    message = update.effective_message
    assert message is not None
    await message.reply_text(
        t(_lang(update, context), "Choose your language:"),
        reply_markup=_language_keyboard(),
    )


async def mysubscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ensure_user(update, context)
    lang = _lang(update, context)
    user = update.effective_user
    assert user is not None
    subs = _db(context).user_subscriptions(user.id)
    message = update.effective_message
    assert message is not None
    if not subs:
        await message.reply_text(t(lang, "You don't follow any school yet."))
        return
    text = t(lang, "Schools you follow:") + "\n" + "\n".join(f"• {s.name}" for s in subs)
    await message.reply_text(text)


async def _change_subscription(
    update: Update, context: ContextTypes.DEFAULT_TYPE, subscribe: bool
) -> None:
    _ensure_user(update, context)
    lang = _lang(update, context)
    message = update.effective_message
    assert message is not None
    user = update.effective_user
    assert user is not None
    if not context.args:
        await message.reply_text(
            t(lang, "Please give a school name or ID, e.g. /subscribe 2")
        )
        return
    database = _db(context)
    school = database.find_school(" ".join(context.args))
    if school is None:
        await message.reply_text(
            t(lang, "I couldn't find a school matching {query}. Use /schools to browse all schools.",
              query=" ".join(context.args))
        )
        return
    if subscribe:
        created = database.subscribe(user.id, school.id)
        key = "Subscribed to {name}." if created else "You're already subscribed to {name}."
    else:
        removed = database.unsubscribe(user.id, school.id)
        key = "Unsubscribed from {name}." if removed else "You're not subscribed to {name}."
    await message.reply_text(t(lang, key, name=school.name))


async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_subscription(update, context, subscribe=True)


async def unsubscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _change_subscription(update, context, subscribe=False)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ensure_user(update, context)
    lang = _lang(update, context)
    lines = [
        t(lang, "Available commands:"),
        t(lang, "/start - set up your language and school subscriptions"),
        t(lang, "/schools - change the schools you follow"),
        t(lang, "/subscribe <school> - follow a school"),
        t(lang, "/unsubscribe <school> - stop following a school"),
        t(lang, "/mysubscriptions - list the schools you follow"),
        t(lang, "/addpage - suggest a Facebook page to watch"),
        t(lang, "/mypages - list pages you suggested and their status"),
        t(lang, "/language - change language (EN/VI)"),
        t(lang, "/help - show this help"),
    ]
    message = update.effective_message
    assert message is not None
    await message.reply_text("\n".join(lines))


# ---------------------------------------------------------------------------
# /addpage — suggest a Facebook page (goes to the admin moderation queue)
# ---------------------------------------------------------------------------

async def addpage_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _ensure_user(update, context)
    lang = _lang(update, context)
    message = update.effective_message
    assert message is not None
    await message.reply_text(
        t(lang, "Send me the Facebook page link or numeric Page ID you want to suggest.")
        + "\n"
        + t(lang, "You can type /cancel anytime to stop.")
    )
    return WAITING_PAGE


async def addpage_got_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = _lang(update, context)
    message = update.effective_message
    assert message is not None
    parsed = parse_facebook_page_ref(message.text or "")
    if parsed is None:
        await message.reply_text(
            t(lang, "I couldn't understand that as a Facebook page. Send a facebook.com link or a numeric Page ID.")
        )
        return WAITING_PAGE
    context.user_data["addpage_ref"] = parsed
    await message.reply_text(
        t(lang, "Got it. Add a short note about this page (e.g. which school it's for), or /skip.")
    )
    return WAITING_NOTE


async def _finish_addpage(
    update: Update, context: ContextTypes.DEFAULT_TYPE, note: str
) -> int:
    database = _db(context)
    settings = _settings(context)
    user = update.effective_user
    assert user is not None
    message = update.effective_message
    assert message is not None
    lang = _lang(update, context)

    kind, ref = context.user_data.pop("addpage_ref")
    context.user_data.pop("addpage_note", None)

    schools = database.list_schools()
    if not schools:
        await message.reply_text(
            t(lang, "No schools are available yet. An admin needs to add schools first — please check back later.")
        )
        return ConversationHandler.END
    # Attach the suggestion to the user's first subscribed school, else the
    # first school overall; the admin can reassign at approval time.
    subs = database.user_subscriptions(user.id)
    school = subs[0] if subs else schools[0]

    if kind == "username":
        await message.reply_text(
            t(lang, "I couldn't understand that as a Facebook page. Send a facebook.com link or a numeric Page ID.")
        )
        return ConversationHandler.END

    try:
        page = database.add_page_submission(
            school_id=school.id,
            fb_page_id=ref,
            page_name=ref,
            added_by_chat_id=user.id,
            note=note,
        )
    except ValueError:
        await message.reply_text(
            t(lang, "You already suggested this page — it's currently {status}.",
              status=t(lang, "pending review"))
        )
        return ConversationHandler.END

    await message.reply_text(
        t(lang, "Thanks! Your suggestion is waiting for admin review. I'll notify you when it's approved.")
    )

    # Notify admins (best effort — they may never have started the bot).
    admin_text = (
        f"📥 New page suggestion #{page.id}\n"
        f"School: {school.name}\n"
        f"FB page ID: {ref}\n"
        f"{t('en', 'Suggested by {user}', user=f'{user.full_name} ({user.id})')}\n"
        + (f"{t('en', 'Note: {note}', note=note)}\n" if note else "")
        + "Review with /pendingpages"
    )
    for admin_id in settings.admin_chat_ids:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_text)
        except Exception:
            LOG.warning("Could not notify admin %s about page suggestion", admin_id)
    return ConversationHandler.END


async def addpage_got_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    message = update.effective_message
    assert message is not None
    return await _finish_addpage(update, context, note=message.text or "")


async def addpage_skip_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _finish_addpage(update, context, note="")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("addpage_ref", None)
    message = update.effective_message
    assert message is not None
    await message.reply_text(t(_lang(update, context), "Cancelled."))
    return ConversationHandler.END


async def mypages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ensure_user(update, context)
    lang = _lang(update, context)
    user = update.effective_user
    assert user is not None
    pages = _db(context).user_pages(user.id)
    message = update.effective_message
    assert message is not None
    if not pages:
        await message.reply_text(t(lang, "You haven't suggested any pages yet."))
        return
    status_key = {
        "pending": "pending review",
        "approved": "approved",
        "rejected": "rejected",
        "disabled": "disabled",
    }
    lines = [t(lang, "Pages you suggested:")]
    for page in pages:
        lines.append(
            f"• {page.page_name} ({page.school_name}) — "
            f"{t(lang, status_key.get(page.status, page.status))}"
        )
    await message.reply_text("\n".join(lines))


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _ensure_user(update, context)
    message = update.effective_message
    assert message is not None
    await message.reply_text(t(_lang(update, context), "This bot only understands commands — try /help."))


def build_addpage_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("addpage", addpage_start)],
        states={
            WAITING_PAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addpage_got_page)],
            WAITING_NOTE: [
                CommandHandler("skip", addpage_skip_note),
                MessageHandler(filters.TEXT & ~filters.COMMAND, addpage_got_note),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )


def register_user_handlers(app: Application, settings: Settings, database: Database) -> None:
    app.bot_data["db"] = database
    app.bot_data["settings"] = settings
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("schools", schools_cmd))
    app.add_handler(CommandHandler("language", language_cmd))
    app.add_handler(CommandHandler("mysubscriptions", mysubscriptions))
    app.add_handler(CommandHandler("subscribe", subscribe_cmd))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe_cmd))
    app.add_handler(CommandHandler("mypages", mypages))
    app.add_handler(CallbackQueryHandler(language_chosen, pattern=r"^lang:(en|vi)$"))
    app.add_handler(CallbackQueryHandler(school_toggled, pattern=r"^school:toggle:\d+$"))
    app.add_handler(CallbackQueryHandler(school_done, pattern=r"^school:done$"))
    app.add_handler(build_addpage_conversation())
    # Catch-all for stray text must come last (admin handlers register their own).
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
