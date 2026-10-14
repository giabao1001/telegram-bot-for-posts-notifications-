# DiemRenLuyen v2

A **public multi-user Telegram bot** that notifies Vietnamese university students
about school events posted on Facebook — so they never miss events that count
toward their training points (*điểm rèn luyện*).

Anyone can `/start` the bot, pick their language (English / Tiếng Việt) and
their school(s). The bot polls each school's curated Facebook pages and
forwards new event posts to every subscriber of that school. Users can also
suggest Facebook pages to watch; suggestions wait in a moderation queue until
an admin approves them.

This is a ground-up redesign of the original single-owner
[diemRenLuyen](https://github.com/giabao1001/telegram-bot-for-posts-notifications-)
monitor: the polling/dedupe/Telegram-send engine is reused, but everything
around it (users, schools, subscriptions, moderation, hosting) is new.

---

## ⚠️ Read this first: the Facebook dependency

Reading a Facebook Page that **you do not manage** requires Meta's
**Page Public Content Access** feature. That means:

- creating a Meta developer app,
- requesting the feature, and
- passing Meta's **app review** (business verification is often required).

**Approval is controlled by Meta and is not guaranteed.** Without it, the bot
can only read Pages whose access tokens your app/user is authorized for
(typically Pages you manage).

The bot is designed honestly around this constraint:

- every Page carries its **own access token** (Fernet-encrypted at rest);
- a Page that Meta refuses to serve is recorded with its error, retried on
  later cycles, and **auto-disabled after 5 consecutive failures** so one bad
  Page never stops the rest;
- only **admin-approved** Pages are ever polled — user suggestions stay in the
  moderation queue until an admin attaches a working token.

Do not expect the bot to read arbitrary public Pages without that Meta
approval. Plan your launch around it: get the approval first, or start with
Pages you manage.

## Architecture

```text
                    ┌─────────────────────┐
                    │  Meta Graph API     │
                    │  /{page}/posts     │
                    └────────┬────────────┘
                             │  poll every N seconds (worker thread)
                             ▼
                    ┌─────────────────────┐
                    │  engine.poll_once   │──► seen_posts(page_id, fb_post_id)
                    │  dedupe + baseline │    (per-page, SQLite)
                    └────────┬────────────┘
                             │ new posts
                             ▼
                    ┌─────────────────────┐
                    │ engine.plan_deliveries│──► subscribers_for_school
                    │ per-user language   │
                    └────────┬────────────┘
                             │ asyncio fan-out (chunked, ~10 concurrent)
                             ▼
                 ┌───────────────────────┐
                 │ Telegram subscribers  │
                 │ EN or VI message each │
                 └───────────────────────┘

  ┌──────────────┐   /start, /schools, /subscribe…    ┌──────────────┐
  │  Subscribers │ ◄──────────────────────────────► │  PTB bot     │
  └──────────────┘                                   │  (asyncio)   │
                                                     └──────────────┘
  ┌──────────────┐   /pendingpages, /approvepage…     (admin chat IDs)
  │    Admins    │ ◄──────────────────────────────►  from ADMIN_CHAT_IDS
  └──────────────┘
```

**Data model (SQLite, `data/bot.db`):**

| table | purpose |
|---|---|
| `users` | `chat_id`, `language` (en/vi), `is_active` (auto-cleared if the user blocks the bot) |
| `schools` | `id`, `name` |
| `pages` | `school_id`, `fb_page_id`, `page_name`, `token_encrypted`, `status` (pending/approved/rejected/disabled), `added_by_chat_id`, `note`, `last_error`, `consecutive_failures` |
| `subscriptions` | `(user_chat_id, school_id)` |
| `seen_posts` | `(page_id, fb_post_id)` — dedupe, scoped per page |
| `initialized_pages` | first-sync baseline per page |

A Postgres migration later means swapping the connection factory and the `?`
placeholders (psycopg uses `%s`); the `Database` method signatures can stay.

## Project layout

```text
diemrenluyen_v2/
  __init__.py     package version
  config.py       env/.env loading + validation
  crypto.py       Fernet encrypt/decrypt for Page tokens
  i18n.py         English/Vietnamese strings
  db.py           SQLite schema + data-access layer
  meta.py         Meta Graph API client
  messages.py     post → Telegram HTML formatting, FB link parsing
  engine.py       poll_once (dedupe) + plan_deliveries (fan-out)
  bot.py          user commands + onboarding flows (python-telegram-bot)
  admin.py        admin-only moderation/management commands
  admin_cli.py    terminal CLI for bootstrapping (no Telegram needed)
  main.py         entrypoint: bot + background poll loop
tests/            pytest suite (dedupe, fan-out, moderation, i18n, config)
Dockerfile, docker-compose.yml   always-on hosting
```

## Quick start

### 1. Create the Telegram bot

1. Message `@BotFather` on Telegram → `/newbot` → pick a name and username.
2. Copy the bot token. **Never commit it.**

### 2. Configure

```bash
cp .env.example .env
# edit .env:
#   TELEGRAM_BOT_TOKEN=...        (from BotFather)
#   ADMIN_CHAT_IDS=123456789      (your Telegram numeric ID; message @userinfobot to get it)
#   CONFIG_ENCRYPTION_KEY=...     (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
```

See `.env.example` for all options (`POLL_INTERVAL_SECONDS`,
`INITIAL_SYNC=skip|send`, `DEFAULT_LANGUAGE`, …).

### 3a. Run with Docker (recommended — always-on)

```bash
docker compose up -d --build
docker compose logs -f
```

The SQLite database persists in `./data/`.

### 3b. Run from source

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m diemrenluyen_v2.admin_cli init-db
python -m diemrenluyen_v2.main
```

The process must stay running (that's the point of the Docker setup): the
poll loop lives inside the bot process.

### 4. Bootstrap content (terminal, no Telegram needed)

```bash
# add schools
python -m diemrenluyen_v2.admin_cli add-school "Đại học Bách Khoa TP.HCM"
python -m diemrenluyen_v2.admin_cli list-schools

# add a curated page (needs a Page access token — see the Facebook note above)
python -m diemrenluyen_v2.admin_cli add-page --school 1 \
  --fb-page-id 123456789 --token <PAGE_ACCESS_TOKEN> --name "Phòng Công tác Sinh viên"
```

Or do it from Telegram as an admin (see below).

## Command reference

### For students

| command | what it does |
|---|---|
| `/start` | choose language, then pick school(s) to follow |
| `/schools` | change the schools you follow (tap to toggle, then Done) |
| `/subscribe <school>` | follow one school by name or ID |
| `/unsubscribe <school>` | stop following a school |
| `/mysubscriptions` | list the schools you follow |
| `/addpage` | suggest a Facebook page to watch (goes to admin review) |
| `/mypages` | see your suggestions and their status |
| `/language` | switch English ↔ Tiếng Việt |
| `/help` | list commands |

### For admins (chat IDs in `ADMIN_CHAT_IDS`)

| command | what it does |
|---|---|
| `/pendingpages` | list user-submitted pages awaiting review |
| `/approvepage <id>` | approve a suggestion — the bot then asks you for the Page access token, verifies it with Meta, and starts polling |
| `/rejectpage <id>` | reject a suggestion (the submitter is notified) |
| `/addschool <name>` | add a school |
| `/addpageadmin <school_id> <fb_page_id_or_link> <token> [name]` | add + approve a page in one step |
| `/listschools`, `/listpages [school_id]` | inspect content |
| `/disablepage <id>` / `/enablepage <id>` | pause / resume polling a page |
| `/broadcast <message>` | message all active users |
| `/stats` | users, schools, pages, subscriptions |

**Getting a Page access token:** create an app at
[Meta for Developers](https://developers.facebook.com/), generate a user token
with `pages_show_list` + `pages_read_engagement`, then in Graph API Explorer
call `GET /me/accounts?fields=id,name,access_token` and copy the Page's
`access_token`. For unattended use, exchange it for a long-lived token. For
Pages you don't manage, you additionally need the Page Public Content Access
approval described above.

## How notifications work

1. Every `POLL_INTERVAL_SECONDS` (min 60s) the engine reads each **approved**
   page's 25 most recent posts via the Graph API.
2. Post IDs are compared against `seen_posts`; only unseen posts continue.
   On a page's **first** poll, `INITIAL_SYNC=skip` silently baselines existing
   posts; `send` forwards up to 25 recent ones.
3. Each new post is fanned out to **active subscribers of that page's school**,
   formatted in each subscriber's language (HTML, with a link back to
   Facebook).
4. If a user blocks the bot, Telegram returns `Forbidden` and the user is
   marked inactive (they reactivate on next `/start`).

## Development & testing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m py_compile diemrenluyen_v2/*.py tests/*.py
```

Tests cover: subscription model, page moderation lifecycle, per-page dedupe,
initial-sync modes, Meta-failure auto-disable, fan-out to the right schools in
the right languages, i18n coverage (every key translated), message formatting
(HTML escaping, truncation), Facebook link parsing, and settings validation.
They use throwaway SQLite databases and a scripted fake Meta client — no
network, no tokens.

## Security notes

- Facebook Page tokens are Fernet-encrypted before touching SQLite. Back up
  `.env` together with `data/bot.db` — losing `CONFIG_ENCRYPTION_KEY` means
  re-entering every token.
- `.env` and `data/` are never committed (add them to `.gitignore`).
- Admin commands are gated on `ADMIN_CHAT_IDS`; the approve flow asks for the
  token in chat — delete that message afterwards.
- Broadcasts go only to users who started the bot and haven't blocked it.

## Limitations / roadmap

- Facebook ingestion is the hard external dependency (see top of this file).
- SQLite is fine for thousands of users; move to Postgres if you outgrow it.
- No keyword filtering yet (e.g. "only posts mentioning học bổng") — a natural
  next feature on top of `plan_deliveries`.
- Page suggestions attach to the suggester's first subscribed school; admins
  can already see the note and curate accordingly.

## License

MIT — see [LICENSE](LICENSE). Independent open-source project; not affiliated
with, endorsed by, or sponsored by Meta or Telegram.
