from __future__ import annotations

import getpass
import secrets
from pathlib import Path

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"


def main() -> None:
    print("PagePulse first-time setup")
    print("This creates the private keys used by your local dashboard.\n")

    if ENV_FILE.exists():
        answer = input(".env already exists. Replace it? [y/N] ").strip().lower()
        if answer != "y":
            print("Nothing changed.")
            return

    while True:
        password = getpass.getpass("Choose a dashboard password (12+ characters): ")
        if len(password) < 12:
            print("Please use at least 12 characters.")
            continue
        confirmation = getpass.getpass("Repeat the password: ")
        if not secrets.compare_digest(password, confirmation):
            print("The passwords did not match. Try again.")
            continue
        break

    values = {
        "DASHBOARD_PASSWORD_HASH": generate_password_hash(password),
        "FLASK_SECRET_KEY": secrets.token_hex(32),
        "CONFIG_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "DATABASE_FILE": "data/notifier.db",
        "HOST": "127.0.0.1",
        "PORT": "8000",
        "COOKIE_SECURE": "0",
    }
    # Single quotes keep characters such as '$' in password hashes literal for
    # both python-dotenv and Docker Compose.
    body = "\n".join(f"{key}='{value}'" for key, value in values.items()) + "\n"
    ENV_FILE.write_text(body, encoding="utf-8")
    print("\nSetup complete. Start PagePulse with: python dashboard.py")
    print("Then open: http://127.0.0.1:8000")


if __name__ == "__main__":
    main()
