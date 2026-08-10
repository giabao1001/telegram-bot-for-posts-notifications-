from __future__ import annotations

import os
import re
import secrets
import threading
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, abort, flash, has_request_context, redirect, render_template, request, session, url_for
from waitress import serve
from werkzeug.security import check_password_hash

from app import FacebookPage, MetaClient, SeenPostStore, TelegramClient, poll_once_detailed
from storage import DashboardStore
from translations import translate


SOURCE_ROOT = Path(__file__).resolve().parent
ASSET_ROOT = Path(os.getenv("DIEMRENLUYEN_ASSET_DIR", SOURCE_ROOT))
DATA_ROOT = Path(os.getenv("DIEMRENLUYEN_DATA_DIR", SOURCE_ROOT))
load_dotenv(DATA_ROOT / ".env")


def required_env(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"{name} is missing. Run: python setup.py")
    return value


app = Flask(
    __name__,
    template_folder=str(ASSET_ROOT / "templates"),
    static_folder=str(ASSET_ROOT / "static"),
)
app.config.update(
    SECRET_KEY=required_env("FLASK_SECRET_KEY"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=32 * 1024,
)

database_setting = Path(os.getenv("DATABASE_FILE", "data/notifier.db"))
DATABASE_PATH = database_setting if database_setting.is_absolute() else DATA_ROOT / database_setting
STORE = DashboardStore(DATABASE_PATH, required_env("CONFIG_ENCRYPTION_KEY"))
DASHBOARD_PASSWORD_HASH = required_env("DASHBOARD_PASSWORD_HASH")
POLL_LOCK = threading.Lock()
STOP_EVENT = threading.Event()


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return str(session["csrf_token"])


def current_language() -> str:
    if not has_request_context():
        return "en"
    return session.get("language", "en") if session.get("language") in {"en", "vi"} else "en"


def t(text: str, **values: object) -> str:
    return translate(current_language(), text, **values)


app.jinja_env.globals.update(csrf_token=csrf_token, current_language=current_language, t=t)


@app.before_request
def protect_dashboard():
    if request.endpoint in {"login", "static", "health", "set_language"}:
        return None
    if not session.get("authenticated"):
        return redirect(url_for("login"))
    if request.method == "POST" and not secrets.compare_digest(
        request.form.get("csrf_token", ""), csrf_token()
    ):
        abort(400, "Invalid CSRF token")
    return None


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/language/<language>")
def set_language(language: str):
    if language not in {"en", "vi"}:
        abort(404)
    session["language"] = language
    destination = request.args.get("next", "")
    if not destination.startswith("/") or destination.startswith("//"):
        destination = url_for("dashboard" if session.get("authenticated") else "login")
    return redirect(destination)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        supplied = request.form.get("password", "")
        if check_password_hash(DASHBOARD_PASSWORD_HASH, supplied):
            language = current_language()
            session.clear()
            session["language"] = language
            session["authenticated"] = True
            csrf_token()
            return redirect(url_for("dashboard"))
        time.sleep(0.4)
        flash(t("That password is not correct."), "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    language = current_language()
    session.clear()
    session["language"] = language
    return redirect(url_for("login"))


@app.get("/")
def dashboard():
    settings = STORE.get_settings()
    pages = STORE.list_pages()
    ready = bool(
        settings.get("telegram_bot_token")
        and settings.get("telegram_chat_id")
        and pages
    )
    return render_template(
        "dashboard.html",
        settings=settings,
        pages=pages,
        activity=STORE.recent_activity(),
        ready=ready,
        running=POLL_LOCK.locked(),
    )


@app.post("/settings")
def save_settings():
    try:
        interval = int(request.form.get("poll_interval_seconds", "300"))
    except ValueError:
        flash(t("Polling interval must be a number."), "error")
        return redirect(url_for("dashboard", _anchor="telegram"))
    initial_sync = request.form.get("initial_sync", "skip")
    if initial_sync not in {"skip", "send"}:
        abort(400)
    graph_version = request.form.get("graph_api_version", "v26.0").strip()
    if not re.fullmatch(r"v\d+\.\d+", graph_version):
        flash(t("Graph API version should look like v26.0."), "error")
        return redirect(url_for("dashboard", _anchor="telegram"))
    chat_id = request.form.get("telegram_chat_id", "").strip()
    if chat_id and not re.fullmatch(r"-?\d+", chat_id):
        flash(t("Telegram Chat ID must contain only digits, with an optional minus sign."), "error")
        return redirect(url_for("dashboard", _anchor="telegram"))
    STORE.save_settings(
        telegram_bot_token=request.form.get("telegram_bot_token") or None,
        telegram_chat_id=chat_id,
        graph_api_version=graph_version,
        poll_interval_seconds=interval,
        initial_sync=initial_sync,
    )
    STORE.log("success", "Connection settings updated")
    flash(t("Settings saved."), "success")
    return redirect(url_for("dashboard", _anchor="telegram"))


@app.post("/pages")
def add_page():
    page_id = request.form.get("page_id", "").strip()
    access_token = request.form.get("access_token", "").strip()
    custom_label = request.form.get("label", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{2,100}", page_id):
        flash(t("Enter a valid numeric Page ID."), "error")
        return redirect(url_for("dashboard", _anchor="pages"))
    if not access_token:
        flash(t("A Page access token is required."), "error")
        return redirect(url_for("dashboard", _anchor="pages"))
    settings = STORE.get_settings()
    try:
        page_name = MetaClient(settings["graph_api_version"]).get_page_name(
            FacebookPage(page_id, access_token)
        )
    except Exception as exc:
        STORE.log("error", f"Could not add Page {page_id}: access check failed")
        flash(t("Meta could not verify this Page: {error}", error=exc), "error")
        return redirect(url_for("dashboard", _anchor="pages"))
    STORE.add_page(page_id, custom_label or page_name, access_token)
    STORE.log("success", f"Added Facebook Page: {custom_label or page_name}")
    flash(t("{name} is now being watched.", name=custom_label or page_name), "success")
    return redirect(url_for("dashboard", _anchor="pages"))


@app.post("/pages/<page_id>/delete")
def remove_page(page_id: str):
    STORE.remove_page(page_id)
    STORE.log("warning", f"Removed Facebook Page {page_id}")
    flash(t("Page removed."), "success")
    return redirect(url_for("dashboard", _anchor="pages"))


@app.post("/telegram/test")
def test_telegram():
    config = STORE.build_config()
    if not config.telegram_bot_token or not config.telegram_chat_id:
        flash(t("Save a bot token and chat ID first."), "error")
        return redirect(url_for("dashboard", _anchor="telegram"))
    try:
        TelegramClient(config.telegram_bot_token, config.telegram_chat_id).send(
            "✅ diemRenLuyen is connected. Facebook alerts will arrive here."
            if current_language() == "en"
            else "✅ diemRenLuyen đã kết nối. Thông báo Facebook sẽ được gửi đến đây."
        )
    except Exception as exc:
        STORE.log("error", "Telegram connection test failed")
        flash(str(exc), "error")
    else:
        STORE.log("success", "Telegram connection test succeeded")
        flash(t("Test notification sent."), "success")
    return redirect(url_for("dashboard", _anchor="telegram"))


@app.post("/telegram/find-chats")
def find_chats():
    token = STORE.get_settings().get("telegram_bot_token", "")
    if not token:
        flash(t("Save the Telegram bot token first."), "error")
        return redirect(url_for("dashboard", _anchor="telegram"))
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates", timeout=30
        )
        payload = response.json()
        if not response.ok or not payload.get("ok"):
            raise RuntimeError(payload.get("description", "Telegram request failed"))
        chats: dict[str, str] = {}
        for update in payload.get("result", []):
            message = update.get("message") or update.get("channel_post") or {}
            chat = message.get("chat") or {}
            if "id" in chat:
                label = chat.get("title") or chat.get("username") or chat.get("first_name") or "chat"
                chats[str(chat["id"])] = str(label)
        if not chats:
            flash(t("No chats found. Send /start to the bot, then try again."), "warning")
        elif len(chats) == 1:
            chat_id, label = next(iter(chats.items()))
            STORE.set_setting("telegram_chat_id", chat_id)
            STORE.log("success", f"Telegram destination saved: {label}")
            flash(t("Found and saved {name} (Chat ID {chat_id}).", name=label, chat_id=chat_id), "success")
        else:
            found = ", ".join(f"{label}: {chat_id}" for chat_id, label in chats.items())
            flash(t("Multiple chats found. Copy the one you want into Chat ID: {chats}", chats=found), "success")
    except Exception as exc:
        flash(str(exc), "error")
    return redirect(url_for("dashboard", _anchor="telegram"))


def perform_poll(source: str) -> None:
    if not POLL_LOCK.acquire(blocking=False):
        raise RuntimeError("A check is already running")
    try:
        config = STORE.build_config()
        if not config.telegram_bot_token or not config.telegram_chat_id:
            raise RuntimeError("Telegram is not configured")
        if not config.pages:
            raise RuntimeError("No Facebook Pages have been added")
        seen_store = SeenPostStore(config.database_path)
        try:
            result = poll_once_detailed(config, seen_store)
        finally:
            seen_store.close()
        summary = (
            f"Checked {result.pages_checked} Page(s); sent {result.sent} alert(s)"
        )
        if result.skipped:
            summary += f"; established a baseline from {result.skipped} existing post(s)"
        if result.errors:
            summary += f"; {len(result.errors)} error(s)"
            STORE.log("warning", summary)
            for error in result.errors:
                STORE.log("error", error)
        else:
            STORE.log("success", summary)
        STORE.update_check_status(summary)
    except Exception as exc:
        STORE.update_check_status(f"Check failed: {exc}")
        STORE.log("error", f"{source.capitalize()} check failed: {exc}")
        raise
    finally:
        POLL_LOCK.release()


@app.post("/poll")
def poll_now():
    try:
        perform_poll("manual")
    except Exception as exc:
        flash(str(exc), "error")
    else:
        flash(t("Facebook check completed."), "success")
    return redirect(url_for("dashboard"))


@app.post("/toggle")
def toggle():
    enabled = STORE.get_setting("enabled", "1") == "1"
    STORE.set_setting("enabled", "0" if enabled else "1")
    STORE.log("warning" if enabled else "success", "Automatic checks paused" if enabled else "Automatic checks resumed")
    flash(t("Automatic checks paused." if enabled else "Automatic checks resumed."), "success")
    return redirect(url_for("dashboard"))


def scheduler_loop() -> None:
    last_started = 0.0
    while not STOP_EVENT.wait(5):
        if STORE.get_setting("enabled", "1") != "1":
            continue
        try:
            interval = max(30, int(STORE.get_setting("poll_interval_seconds", "300")))
        except ValueError:
            interval = 300
        if time.monotonic() - last_started < interval:
            continue
        last_started = time.monotonic()
        try:
            perform_poll("automatic")
        except Exception:
            continue


def main() -> None:
    scheduler = threading.Thread(target=scheduler_loop, daemon=True, name="page-poller")
    scheduler.start()
    port = int(os.getenv("PORT", "8000"))
    try:
        serve(app, host=os.getenv("HOST", "127.0.0.1"), port=port, threads=6)
    finally:
        STOP_EVENT.set()


if __name__ == "__main__":
    main()
