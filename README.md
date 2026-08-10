# diemRenLuyen

diemRenLuyen is a private Facebook Page monitor that sends new Page posts to a
Telegram conversation. It includes a local browser dashboard, encrypted credential
storage, automatic polling, deduplication, English and Vietnamese interfaces, and
desktop launchers for Windows and macOS.

The application runs on your computer. Telegram is the notification destination;
the dashboard is not a Telegram Mini App. Your computer must be awake and connected
to the internet while monitoring.

## Features

- Monitors Facebook Pages through the official Meta Graph API
- Sends each new post once through the Telegram Bot API
- Supports private chats, groups, and channels
- Finds and saves a Telegram Chat ID from recent bot conversations
- Offers English and Vietnamese with one-click `EN` / `VI` controls
- Encrypts Telegram and Facebook tokens before storing them in SQLite
- Includes configurable polling and first-sync behavior
- Provides one-click desktop launchers and sign-in auto-start
- Supports Windows, macOS, Linux, and Docker
- Builds downloadable Windows and macOS packages through GitHub Releases

## How it works

```text
Meta Graph API
      │
      ▼
diemRenLuyen background service
      │
      ├── records seen post IDs in local SQLite storage
      │
      ▼
Telegram Bot API ──► private chat, group, or channel
```

The service polls every 1, 5, 15, 30, or 60 minutes. On the first check, it can
silently establish a baseline or send up to 25 recent posts. Later checks compare
post IDs with the local database and send only posts that have not been seen.

## Download for Windows or macOS

Open the repository's [Releases page](https://github.com/giabao1001/telegram-bot-for-posts-notifications-/releases)
and download the archive for your operating system:

- `diemRenLuyen-Windows.zip` contains the standalone Windows executable.
- `diemRenLuyen-macOS.zip` contains the standalone macOS application.

Release files are created automatically when a version tag such as `v1.0.0` is
pushed. Until the first tagged release is published, use the source installation
instructions below.

### Windows desktop application

1. Download and extract `diemRenLuyen-Windows.zip`.
2. Double-click `diemRenLuyen.exe`.
3. Choose and confirm a dashboard password of at least 12 characters.
4. Select **Start / Open Dashboard**.
5. Select **Enable auto-start** if you want it to start when you sign in to Windows.

The desktop window can be closed after the service starts. The service continues in
the background without a Command Prompt or PowerShell window. Open the executable
again to open the dashboard, stop the service, or change automatic startup.

Windows may show a Microsoft Defender SmartScreen warning because community builds
are not code-signed. Verify that the download came from this repository's Releases
page before choosing **More info → Run anyway**.

Application data is stored under:

```text
%LOCALAPPDATA%\diemRenLuyen
```

### macOS desktop application

1. Download and extract `diemRenLuyen-macOS.zip`.
2. Open `diemRenLuyen.app`.
3. Choose and confirm a dashboard password of at least 12 characters.
4. Select **Start / Open Dashboard**.
5. Select **Enable auto-start** if you want it to start when you sign in to macOS.

If macOS blocks the unsigned community build, Control-click the application, select
**Open**, and confirm that you want to open it. Only do this for a file downloaded
from this repository's Releases page.

Application data is stored under:

```text
~/Library/Application Support/diemRenLuyen
```

## Install from source

Python 3.11 or newer is required.

### macOS or Linux

```bash
git clone https://github.com/giabao1001/telegram-bot-for-posts-notifications-.git
cd telegram-bot-for-posts-notifications-
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python setup.py
python dashboard.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

On macOS, build and use the no-Terminal launcher:

```bash
./scripts/build_macos_launcher.sh
open "diemRenLuyen Launcher.app"
```

Enable automatic startup for the source installation:

```bash
.venv/bin/python pagepulse_launcher.py install-autostart
```

Disable it later with:

```bash
.venv/bin/python pagepulse_launcher.py uninstall-autostart
```

### Windows PowerShell

```powershell
git clone https://github.com/giabao1001/telegram-bot-for-posts-notifications-.git
cd telegram-bot-for-posts-notifications-
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python setup.py
python dashboard.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Developers can also run `desktop_launcher.py` to exercise the desktop launcher from
source. The packaged Windows release uses the same launcher without displaying a
terminal window.

### Linux

Linux uses the source commands above. For unattended operation, create a systemd
user service or use Docker. The browser dashboard and notifier themselves are not
macOS- or Windows-specific.

## First-time dashboard setup

`setup.py` creates `.env` with:

- a password hash for dashboard sign-in;
- a random Flask session key;
- a Fernet encryption key for saved credentials;
- the local database path and network settings.

Keep `.env` private and back it up together with `data/notifier.db`. The database
cannot decrypt saved tokens without the original `CONFIG_ENCRYPTION_KEY`.

## Change between English and Vietnamese

Select `EN` or `VI` in the upper-right corner of the login page or dashboard. The
preference is stored in your private browser session. Navigation, field labels,
validation messages, buttons, and help text update immediately after the click.

## Connect Telegram

### 1. Create a bot

1. Open Telegram and message the verified `@BotFather` account.
2. Send `/newbot`.
3. Choose a display name.
4. Choose a unique username ending in `bot`.
5. Copy the bot token and keep it private.

Anyone who obtains the token can control the bot. Never commit it to Git or include
it in screenshots.

### 2. Start the destination conversation

For a private chat, open the new bot, press **Start**, and send `/start`. A Telegram
bot generally cannot initiate a private conversation before the user contacts it.

For a group, add the bot to the group and send a bot command in that group. For a
channel, add the bot with the permissions needed to post and create an update the
bot can observe.

### 3. Find the Chat ID

1. Open the diemRenLuyen dashboard.
2. Paste the bot token under **Connect Telegram**.
3. Leave Chat ID blank and select **Save settings**.
4. Select **Find and save my chat ID**.
5. If one conversation is found, it is saved automatically.
6. If several are found, copy the desired numeric ID into Chat ID and save again.
7. Select **Send test message**.

A private Chat ID normally looks like `123456789`. Group and channel IDs are often
negative, for example `-1001234567890`. The Chat ID is not a Telegram username and
is not the bot token.

If no conversation is found, send `/start` or another bot command in the desired
conversation and try again.

## Connect a Facebook Page

Meta controls which Pages an access token may read. The application does not scrape
Facebook HTML and never asks for a Facebook password.

### Pages you manage

1. Create an app in [Meta for Developers](https://developers.facebook.com/).
2. Add the Facebook/Business login capability appropriate for the app.
3. Generate a user token with `pages_show_list` and `pages_read_engagement`.
4. In Graph API Explorer, request:

   ```text
   GET /me/accounts?fields=id,name,access_token
   ```

5. Copy the desired Page's numeric `id` and Page `access_token`.
6. In diemRenLuyen, open **Watch Facebook Pages**.
7. Enter the Page ID and Page access token, then select **Verify and add Page**.

Meta verifies the token before diemRenLuyen encrypts and saves it. Explorer tokens
may be short-lived; an always-on installation should use an appropriate long-lived
token supported by Meta.

### Public Pages you do not manage

Reading arbitrary public Page content requires Meta's approved **Page Public Content
Access** feature. App Review and business verification may be required. Approval is
controlled by Meta and is not guaranteed.

## Initial synchronization

The **When adding a Page** option controls the first successful check:

- **Start with the next new post** records existing posts without sending them.
- **Send up to 25 recent posts** sends recent content immediately.

After the baseline is established, saved post IDs prevent duplicate notifications.

## Automatic startup and background behavior

Desktop auto-start is per user and begins after that user signs in:

- Windows uses the current user's standard startup registration.
- macOS uses a per-user LaunchAgent.

Neither mode requires a terminal window. Closing the browser does not stop the
notifier. Sleeping, shutting down, or disconnecting the computer pauses checks until
the service can run again. For uninterrupted 24/7 monitoring, deploy to an always-on
computer or server.

## Docker

Generate `.env` once, then start the container:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python setup.py
docker compose up -d --build
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Useful commands:

```bash
docker compose logs -f
docker compose restart
docker compose down
```

The `data/` directory is mounted into the container so settings and seen-post
history survive restarts.

## Publish GitHub download files

The workflow at `.github/workflows/release.yml` builds on native Windows and macOS
GitHub runners. To publish a release:

```bash
git tag v1.0.0
git push origin v1.0.0
```

After both builds finish, GitHub creates a Release with Windows and macOS `.zip`
downloads and generated release notes. The workflow can also be run manually to
test packaging without publishing a Release.

Production distribution should add Apple Developer ID and Windows Authenticode
signing. The included workflow intentionally does not require private signing keys.

## Security and privacy

- Telegram and Page tokens are encrypted before being stored in SQLite.
- Dashboard writes require authentication and a CSRF token.
- The default host is `127.0.0.1`, so the dashboard is not exposed to the network.
- `.env`, virtual environments, databases, PID files, and logs are ignored by Git.
- Activity messages do not include access tokens.
- There is no public user registration; each installation is private and single-owner.

If a token is committed or shared, revoke and replace it immediately. Removing the
latest copy from Git is insufficient because Git preserves history.

## Troubleshooting

### Telegram: no Chat ID found

Confirm that the saved token belongs to the bot you messaged. Send `/start` to that
bot in the destination conversation, then run the finder again.

### Telegram: `chat not found`

The Chat ID is wrong, the bot was removed, or the bot has not been started in that
conversation. Repeat the Chat ID discovery steps.

### Telegram: `Unauthorized`

The bot token is invalid or was revoked. Generate a replacement through BotFather.

### Facebook: invalid or expired token

Generate a new Page access token and update the Page entry. Use a long-lived token
for unattended monitoring.

### Facebook: permissions error

The token lacks Page permissions, the account/app cannot access the Page, or public
Page access requires Meta App Review.

### Port 8000 is already in use

Stop the other server or the previous diemRenLuyen process. Only one local instance
can use `127.0.0.1:8000` at a time.

### Saved tokens stopped decrypting

Restore the `.env` that was created with the database. If the encryption key is
lost, saved tokens must be entered again.

### Desktop application will not open

Extract the complete `.zip` before opening it. Review the platform warning guidance
above and only bypass unsigned-app warnings for downloads from this repository.

## Development

Install test dependencies and run the checks:

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
python -m py_compile app.py dashboard.py desktop_launcher.py pagepulse_launcher.py storage.py setup.py translations.py
```

Project layout:

```text
app.py                    Facebook and Telegram notification engine
dashboard.py              Flask dashboard and scheduler
desktop_launcher.py       Cross-platform packaged desktop launcher
pagepulse_launcher.py     Source-install macOS process/autostart manager
translations.py           English/Vietnamese UI translations
storage.py                Encrypted SQLite dashboard storage
setup.py                  Source-install first-time setup
templates/                HTML interface
static/                   CSS and JavaScript
macos/                    Source for the macOS launcher app
scripts/                  Local build helpers
tests/                    Automated tests
.github/workflows/        Tests and desktop release builds
```

## License and independence

See [LICENSE](LICENSE). diemRenLuyen is an independent open-source project and is
not affiliated with, endorsed by, or sponsored by Meta or Telegram.
