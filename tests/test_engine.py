"""Tests for the polling engine: dedupe, initial sync, moderation, fan-out."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from diemrenluyen_v2 import engine
from diemrenluyen_v2.crypto import TokenCipher
from diemrenluyen_v2.db import MAX_CONSECUTIVE_FAILURES, STATUS_APPROVED, Database
from diemrenluyen_v2.meta import MetaError


@dataclass
class FakeMeta:
    """Scripted stand-in for MetaClient."""

    pages: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail_with: Exception | None = None

    def get_page_name(self, page_id: str, access_token: str) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        return str(self.pages[page_id]["name"])

    def get_recent_posts(
        self, page_id: str, access_token: str, limit: int = 25
    ) -> list[dict[str, Any]]:
        if self.fail_with is not None:
            raise self.fail_with
        return list(self.pages[page_id]["posts"])


def _post(pid: str, message: str = "hello") -> dict[str, Any]:
    return {
        "id": pid,
        "message": message,
        "created_time": "2026-10-14T10:00:00+0000",
        "permalink_url": f"https://facebook.com/{pid}",
    }


def _setup(db: Database, cipher: TokenCipher, token: str = "tok") -> tuple[int, int]:
    """One school with one approved page; returns (school_id, page_db_id)."""
    school = db.add_school("Uni")
    page = db.add_page_submission(
        school_id=school.id,
        fb_page_id="111",
        page_name="Events",
        added_by_chat_id=None,
        token_encrypted=cipher.encrypt(token),
        status=STATUS_APPROVED,
    )
    return school.id, page.id


def test_poll_returns_new_posts_then_dedupes(
    db: Database, cipher: TokenCipher, settings
) -> None:
    _setup(db, cipher)
    fake = FakeMeta(pages={"111": {"name": "Events", "posts": [_post("p1"), _post("p2")]}})
    result, new_posts = engine.poll_once(db, cipher, settings, meta_factory=lambda v: fake)
    assert result.pages_checked == 1
    assert result.new_posts == 2
    # Graph returns newest first; engine reverses to chronological.
    assert [p.post["id"] for p in new_posts] == ["p2", "p1"]
    # Second poll: nothing new.
    result2, new_posts2 = engine.poll_once(db, cipher, settings, meta_factory=lambda v: fake)
    assert result2.new_posts == 0 and new_posts2 == []


def test_initial_sync_skip_records_without_alerts(
    db: Database, cipher: TokenCipher, settings
) -> None:
    settings = settings  # noqa: F841 - clarity
    import dataclasses

    settings = dataclasses.replace(settings, initial_sync="skip")
    _setup(db, cipher)
    fake = FakeMeta(pages={"111": {"name": "Events", "posts": [_post("p1")]}})
    result, new_posts = engine.poll_once(db, cipher, settings, meta_factory=lambda v: fake)
    assert new_posts == [] and result.skipped_on_first_sync == 1
    # Later posts still alert.
    fake.pages["111"]["posts"] = [_post("p2"), _post("p1")]
    result, new_posts = engine.poll_once(db, cipher, settings, meta_factory=lambda v: fake)
    assert [p.post["id"] for p in new_posts] == ["p2"]


def test_pending_pages_are_not_polled(db: Database, cipher: TokenCipher, settings) -> None:
    school = db.add_school("Uni")
    db.add_page_submission(
        school_id=school.id, fb_page_id="222", page_name="Pending",
        added_by_chat_id=5, token_encrypted=cipher.encrypt("tok"),
    )  # status defaults to pending
    result, new_posts = engine.poll_once(
        db, cipher, settings, meta_factory=lambda v: FakeMeta()
    )
    assert result.pages_checked == 0 and new_posts == []


def test_meta_error_recorded_and_page_auto_disabled(
    db: Database, cipher: TokenCipher, settings
) -> None:
    _, page_id = _setup(db, cipher)
    boom = MetaError("Meta API error (code 10): permission denied")
    for i in range(MAX_CONSECUTIVE_FAILURES):
        result, _ = engine.poll_once(
            db, cipher, settings, meta_factory=lambda v: FakeMeta(fail_with=boom)
        )
    assert len(result.errors) == 1
    assert db.get_page(page_id).status == "disabled"
    assert result.auto_disabled == ["Events"]
    # Disabled pages are skipped entirely afterwards.
    result, _ = engine.poll_once(
        db, cipher, settings, meta_factory=lambda v: FakeMeta(fail_with=boom)
    )
    assert result.pages_checked == 0 and result.errors == []


def test_plan_deliveries_fans_out_per_school_and_language(
    db: Database, cipher: TokenCipher, settings
) -> None:
    school_a = db.add_school("Uni A")
    school_b = db.add_school("Uni B")
    db.upsert_user(1, "en")
    db.upsert_user(2, "vi")
    db.upsert_user(3, "en")
    db.subscribe(1, school_a.id)
    db.subscribe(2, school_a.id)
    db.subscribe(3, school_b.id)

    new_posts = [
        engine.NewPost(
            page_id=9, school_id=school_a.id, school_name="Uni A",
            page_name="Events A", post=_post("p1", "party time"),
        )
    ]
    deliveries = engine.plan_deliveries(db, new_posts)
    by_chat = {d.chat_id: d for d in deliveries}
    assert set(by_chat) == {1, 2}
    assert "party time" in by_chat[1].text
    assert "party time" in by_chat[2].text
    # Vietnamese subscriber gets a Vietnamese header.
    assert "Bài viết sự kiện mới" in by_chat[2].text
    assert "New event post" in by_chat[1].text
