"""Tiny terminal admin CLI for bootstrapping the bot without Telegram.

Examples
--------
  python -m diemrenluyen_v2.admin_cli init-db
  python -m diemrenluyen_v2.admin_cli add-school "Đại học Bách Khoa"
  python -m diemrenluyen_v2.admin_cli list-schools
  python -m diemrenluyen_v2.admin_cli add-page --school 1 --fb-page-id 123456789 --token PAGE_TOKEN --name "Phòng CTSV"
  python -m diemrenluyen_v2.admin_cli list-pages --status approved
"""

from __future__ import annotations

import argparse
import sys

from .config import load_settings
from .crypto import TokenCipher
from .db import STATUS_APPROVED, Database


def _ctx() -> tuple[Database, TokenCipher]:
    settings = load_settings()
    cipher = TokenCipher(settings.encryption_key)
    return Database(settings.database_file), cipher


def cmd_init_db(_: argparse.Namespace) -> int:
    db, _ = _ctx()
    print(f"Database ready at {db.path}")
    return 0


def cmd_add_school(args: argparse.Namespace) -> int:
    db, _ = _ctx()
    try:
        school = db.add_school(args.name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Added school #{school.id}: {school.name}")
    return 0


def cmd_list_schools(_: argparse.Namespace) -> int:
    db, _ = _ctx()
    schools = db.list_schools()
    if not schools:
        print("No schools yet.")
        return 0
    for school in schools:
        print(f"#{school.id}  {school.name}")
    return 0


def cmd_add_page(args: argparse.Namespace) -> int:
    db, cipher = _ctx()
    school = db.get_school(args.school)
    if school is None:
        print(f"Error: no school with ID {args.school}", file=sys.stderr)
        return 1
    try:
        page = db.add_page_submission(
            school_id=school.id,
            fb_page_id=args.fb_page_id,
            page_name=args.name or args.fb_page_id,
            added_by_chat_id=None,
            note=args.note or "",
            token_encrypted=cipher.encrypt(args.token),
            status=STATUS_APPROVED,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Added approved page #{page.id}: {page.page_name} (school: {school.name})")
    print("Note: the token is stored encrypted; it will be verified on the next poll.")
    return 0


def cmd_list_pages(args: argparse.Namespace) -> int:
    db, _ = _ctx()
    pages = db.list_pages(status=args.status)
    if not pages:
        print("No pages yet.")
        return 0
    for page in pages:
        print(f"#{page.id}  [{page.status}] {page.page_name} (fb:{page.fb_page_id}) — {page.school_name}")
    return 0


def cmd_stats(_: argparse.Namespace) -> int:
    db, _ = _ctx()
    print(f"users: {db.count_users()} (active: {db.count_users(active_only=True)})")
    print(f"schools: {len(db.list_schools())}")
    print(f"pages approved: {len(db.list_pages(status=STATUS_APPROVED))}")
    print(f"pages pending: {len(db.list_pages(status='pending'))}")
    print(f"subscriptions: {db.count_subscriptions()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DiemRenLuyen v2 admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create the database schema").set_defaults(func=cmd_init_db)

    p = sub.add_parser("add-school", help="Add a school")
    p.add_argument("name", help="School name")
    p.set_defaults(func=cmd_add_school)

    sub.add_parser("list-schools", help="List schools").set_defaults(func=cmd_list_schools)

    p = sub.add_parser("add-page", help="Add an approved Facebook page directly")
    p.add_argument("--school", type=int, required=True, help="School ID from list-schools")
    p.add_argument("--fb-page-id", required=True, help="Numeric Facebook Page ID")
    p.add_argument("--token", required=True, help="Page access token (stored encrypted)")
    p.add_argument("--name", default="", help="Display name (defaults to the Page ID)")
    p.add_argument("--note", default="", help="Optional note")
    p.set_defaults(func=cmd_add_page)

    p = sub.add_parser("list-pages", help="List pages")
    p.add_argument("--status", default=None, help="Filter: pending/approved/rejected/disabled")
    p.set_defaults(func=cmd_list_pages)

    sub.add_parser("stats", help="Show bot statistics").set_defaults(func=cmd_stats)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
