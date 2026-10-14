"""SQLite data-access layer.

Tables
------
users           chat_id PK, language, is_active, created_at
schools         id PK, name UNIQUE, created_at
pages           id PK, school_id FK, fb_page_id, page_name, token_encrypted,
                status (pending/approved/rejected/disabled), added_by_chat_id,
                note, last_error, consecutive_failures, created_at
subscriptions   (user_chat_id, school_id) PK
seen_posts      (page_id, fb_post_id) PK
initialized_pages  page_id PK

Only *approved* pages are polled. User-submitted pages enter as ``pending``
and become visible to subscribers after an admin approves them with a working
Page access token.

The schema is deliberately plain SQLite. A Postgres migration later means
replacing the connection factory and the ``?`` placeholders (psycopg uses
``%s``); the method signatures can stay the same.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


# Page statuses
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_DISABLED = "disabled"

# A page that fails this many consecutive Meta reads is auto-disabled.
MAX_CONSECUTIVE_FAILURES = 5

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
    chat_id    INTEGER PRIMARY KEY,
    language   TEXT NOT NULL DEFAULT 'en',
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schools (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pages (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id            INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    fb_page_id           TEXT NOT NULL,
    page_name            TEXT NOT NULL,
    token_encrypted      TEXT NOT NULL DEFAULT '',
    status               TEXT NOT NULL DEFAULT 'pending',
    added_by_chat_id     INTEGER,
    note                 TEXT NOT NULL DEFAULT '',
    last_error           TEXT NOT NULL DEFAULT '',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (school_id, fb_page_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_chat_id INTEGER NOT NULL REFERENCES users(chat_id) ON DELETE CASCADE,
    school_id    INTEGER NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_chat_id, school_id)
);

CREATE TABLE IF NOT EXISTS seen_posts (
    page_id    INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    fb_post_id TEXT NOT NULL,
    seen_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (page_id, fb_post_id)
);

CREATE TABLE IF NOT EXISTS initialized_pages (
    page_id        INTEGER PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_pages_status ON pages(status);
CREATE INDEX IF NOT EXISTS idx_pages_school ON pages(school_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_school ON subscriptions(school_id);
"""


@dataclass(frozen=True)
class User:
    chat_id: int
    language: str
    is_active: bool


@dataclass(frozen=True)
class School:
    id: int
    name: str


@dataclass(frozen=True)
class Page:
    id: int
    school_id: int
    school_name: str
    fb_page_id: str
    page_name: str
    status: str
    added_by_chat_id: int | None
    note: str
    last_error: str
    consecutive_failures: int


@dataclass(frozen=True)
class Subscriber:
    chat_id: int
    language: str


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ---------------- users ----------------

    def upsert_user(self, chat_id: int, language: str = "en") -> User:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO users(chat_id, language) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET is_active = 1",
                (chat_id, language),
            )
            row = conn.execute(
                "SELECT chat_id, language, is_active FROM users WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return User(int(row["chat_id"]), str(row["language"]), bool(row["is_active"]))

    def get_user(self, chat_id: int) -> User | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chat_id, language, is_active FROM users WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if row is None:
            return None
        return User(int(row["chat_id"]), str(row["language"]), bool(row["is_active"]))

    def set_language(self, chat_id: int, language: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET language = ? WHERE chat_id = ?", (language, chat_id)
            )

    def set_user_active(self, chat_id: int, active: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE users SET is_active = ? WHERE chat_id = ?",
                (1 if active else 0, chat_id),
            )

    def count_users(self, active_only: bool = False) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM users WHERE (? = 0 OR is_active = 1)",
                (1 if active_only else 0,),
            ).fetchone()
        return int(row["n"])

    def active_chat_ids(self) -> list[int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT chat_id FROM users WHERE is_active = 1").fetchall()
        return [int(r["chat_id"]) for r in rows]

    # ---------------- schools ----------------

    def add_school(self, name: str) -> School:
        name = name.strip()
        if not name:
            raise ValueError("School name must not be empty")
        with self._connect() as conn:
            try:
                cur = conn.execute("INSERT INTO schools(name) VALUES (?)", (name,))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"School {name!r} already exists") from exc
            school_id = cur.lastrowid
        assert school_id is not None
        return School(school_id, name)

    def list_schools(self) -> list[School]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, name FROM schools ORDER BY name").fetchall()
        return [School(int(r["id"]), str(r["name"])) for r in rows]

    def find_school(self, query: str) -> School | None:
        """Find a school by ID or (case-insensitive) name fragment."""
        query = query.strip()
        with self._connect() as conn:
            if query.isdigit():
                row = conn.execute(
                    "SELECT id, name FROM schools WHERE id = ?", (int(query),)
                ).fetchone()
                if row:
                    return School(int(row["id"]), str(row["name"]))
            row = conn.execute(
                "SELECT id, name FROM schools WHERE lower(name) LIKE ? ORDER BY name LIMIT 1",
                (f"%{query.lower()}%",),
            ).fetchone()
        if row is None:
            return None
        return School(int(row["id"]), str(row["name"]))

    def get_school(self, school_id: int) -> School | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name FROM schools WHERE id = ?", (school_id,)
            ).fetchone()
        if row is None:
            return None
        return School(int(row["id"]), str(row["name"]))

    # ---------------- pages ----------------

    def add_page_submission(
        self,
        school_id: int,
        fb_page_id: str,
        page_name: str,
        added_by_chat_id: int | None,
        note: str = "",
        token_encrypted: str = "",
        status: str = STATUS_PENDING,
    ) -> Page:
        with self._connect() as conn:
            try:
                cur = conn.execute(
                    """
                    INSERT INTO pages(school_id, fb_page_id, page_name, token_encrypted,
                                     status, added_by_chat_id, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        school_id,
                        fb_page_id.strip(),
                        page_name.strip() or fb_page_id.strip(),
                        token_encrypted,
                        status,
                        added_by_chat_id,
                        note.strip(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("This page was already added for that school") from exc
            page_id = cur.lastrowid
        assert page_id is not None
        result = self.get_page(page_id)
        assert result is not None
        return result

    def get_page(self, page_id: int) -> Page | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT p.id, p.school_id, s.name AS school_name, p.fb_page_id,
                       p.page_name, p.status, p.added_by_chat_id, p.note,
                       p.last_error, p.consecutive_failures
                FROM pages p JOIN schools s ON s.id = p.school_id
                WHERE p.id = ?
                """,
                (page_id,),
            ).fetchone()
        return self._row_to_page(row)

    def list_pages(
        self, status: str | None = None, school_id: int | None = None
    ) -> list[Page]:
        query = (
            "SELECT p.id, p.school_id, s.name AS school_name, p.fb_page_id, "
            "p.page_name, p.status, p.added_by_chat_id, p.note, "
            "p.last_error, p.consecutive_failures "
            "FROM pages p JOIN schools s ON s.id = p.school_id WHERE 1 = 1"
        )
        params: list[object] = []
        if status is not None:
            query += " AND p.status = ?"
            params.append(status)
        if school_id is not None:
            query += " AND p.school_id = ?"
            params.append(school_id)
        query += " ORDER BY s.name, p.page_name"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [p for r in rows if (p := self._row_to_page(r)) is not None]

    def list_approved_pages(self) -> list[Page]:
        return self.list_pages(status=STATUS_APPROVED)

    def get_page_token_encrypted(self, page_id: int) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT token_encrypted FROM pages WHERE id = ?", (page_id,)
            ).fetchone()
        return str(row["token_encrypted"]) if row else ""

    def approve_page(self, page_id: int, token_encrypted: str, page_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE pages
                SET status = ?, token_encrypted = ?, page_name = ?,
                    last_error = '', consecutive_failures = 0
                WHERE id = ?
                """,
                (STATUS_APPROVED, token_encrypted, page_name, page_id),
            )
            # A re-approved page re-baselines: old "seen" state no longer applies.
            conn.execute("DELETE FROM initialized_pages WHERE page_id = ?", (page_id,))
            conn.execute("DELETE FROM seen_posts WHERE page_id = ?", (page_id,))

    def set_page_status(self, page_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE pages SET status = ? WHERE id = ?", (status, page_id))

    def update_page_name(self, page_id: int, page_name: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE pages SET page_name = ? WHERE id = ?", (page_name, page_id)
            )

    def record_page_failure(self, page_id: int, error: str) -> bool:
        """Record a failed Meta read. Returns True if the page was auto-disabled."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT consecutive_failures FROM pages WHERE id = ?", (page_id,)
            ).fetchone()
            failures = int(row["consecutive_failures"]) + 1 if row else 1
            status = (
                STATUS_DISABLED if failures >= MAX_CONSECUTIVE_FAILURES else STATUS_APPROVED
            )
            conn.execute(
                "UPDATE pages SET last_error = ?, consecutive_failures = ?, status = ? "
                "WHERE id = ?",
                (error[:500], failures, status, page_id),
            )
        return status == STATUS_DISABLED

    def record_page_success(self, page_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE pages SET last_error = '', consecutive_failures = 0 WHERE id = ?",
                (page_id,),
            )

    def user_pages(self, chat_id: int) -> list[Page]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.school_id, s.name AS school_name, p.fb_page_id,
                       p.page_name, p.status, p.added_by_chat_id, p.note,
                       p.last_error, p.consecutive_failures
                FROM pages p JOIN schools s ON s.id = p.school_id
                WHERE p.added_by_chat_id = ?
                ORDER BY p.created_at DESC
                """,
                (chat_id,),
            ).fetchall()
        return [p for r in rows if (p := self._row_to_page(r)) is not None]

    @staticmethod
    def _row_to_page(row: sqlite3.Row | None) -> Page | None:
        if row is None:
            return None
        return Page(
            id=int(row["id"]),
            school_id=int(row["school_id"]),
            school_name=str(row["school_name"]),
            fb_page_id=str(row["fb_page_id"]),
            page_name=str(row["page_name"]),
            status=str(row["status"]),
            added_by_chat_id=(
                int(row["added_by_chat_id"]) if row["added_by_chat_id"] is not None else None
            ),
            note=str(row["note"]),
            last_error=str(row["last_error"]),
            consecutive_failures=int(row["consecutive_failures"]),
        )

    # ---------------- subscriptions ----------------

    def subscribe(self, chat_id: int, school_id: int) -> bool:
        """Returns True if this created a new subscription."""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO subscriptions(user_chat_id, school_id) VALUES (?, ?)",
                (chat_id, school_id),
            )
        return cur.rowcount > 0

    def unsubscribe(self, chat_id: int, school_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM subscriptions WHERE user_chat_id = ? AND school_id = ?",
                (chat_id, school_id),
            )
        return cur.rowcount > 0

    def set_subscriptions(self, chat_id: int, school_ids: list[int]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM subscriptions WHERE user_chat_id = ?", (chat_id,))
            conn.executemany(
                "INSERT INTO subscriptions(user_chat_id, school_id) VALUES (?, ?)",
                [(chat_id, sid) for sid in school_ids],
            )

    def user_subscriptions(self, chat_id: int) -> list[School]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.name FROM schools s
                JOIN subscriptions sub ON sub.school_id = s.id
                WHERE sub.user_chat_id = ?
                ORDER BY s.name
                """,
                (chat_id,),
            ).fetchall()
        return [School(int(r["id"]), str(r["name"])) for r in rows]

    def subscribers_for_school(self, school_id: int) -> list[Subscriber]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT u.chat_id, u.language FROM users u
                JOIN subscriptions sub ON sub.user_chat_id = u.chat_id
                WHERE sub.school_id = ? AND u.is_active = 1
                """,
                (school_id,),
            ).fetchall()
        return [Subscriber(int(r["chat_id"]), str(r["language"])) for r in rows]

    def count_subscriptions(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM subscriptions").fetchone()
        return int(row["n"])

    # ---------------- dedupe ----------------

    def has_seen(self, page_id: int, fb_post_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_posts WHERE page_id = ? AND fb_post_id = ?",
                (page_id, fb_post_id),
            ).fetchone()
        return row is not None

    def mark_seen(self, page_id: int, fb_post_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_posts(page_id, fb_post_id) VALUES (?, ?)",
                (page_id, fb_post_id),
            )

    def is_page_initialized(self, page_id: int) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM initialized_pages WHERE page_id = ?", (page_id,)
            ).fetchone()
        return row is not None

    def mark_page_initialized(self, page_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO initialized_pages(page_id) VALUES (?)", (page_id,)
            )
