"""Tests for the data-access layer: users, schools, pages, subscriptions, dedupe."""

from __future__ import annotations

import pytest

from diemrenluyen_v2.db import (
    MAX_CONSECUTIVE_FAILURES,
    STATUS_APPROVED,
    STATUS_DISABLED,
    STATUS_PENDING,
    Database,
)


def _school_with_page(db: Database, school_name: str = "Test University") -> int:
    school = db.add_school(school_name)
    page = db.add_page_submission(
        school_id=school.id,
        fb_page_id="12345",
        page_name="Test Page",
        added_by_chat_id=111,
        status=STATUS_APPROVED,
        token_encrypted="enc",
    )
    return page.id


def test_user_upsert_and_language(db: Database) -> None:
    user = db.upsert_user(42, "vi")
    assert user.chat_id == 42 and user.language == "vi" and user.is_active
    # Re-upsert keeps the stored language but reactivates.
    db.set_user_active(42, False)
    user = db.upsert_user(42, "en")
    assert user.is_active and user.language == "vi"
    db.set_language(42, "en")
    assert db.get_user(42).language == "en"


def test_school_crud_and_find(db: Database) -> None:
    a = db.add_school("Đại học Bách Khoa")
    b = db.add_school("Đại học Kinh tế")
    assert [s.name for s in db.list_schools()] == ["Đại học Bách Khoa", "Đại học Kinh tế"]
    with pytest.raises(ValueError):
        db.add_school("Đại học Bách Khoa")
    assert db.find_school(str(a.id)).id == a.id
    assert db.find_school("bách khoa").id == a.id
    assert db.find_school("no such school") is None


def test_page_moderation_lifecycle(db: Database) -> None:
    school = db.add_school("Uni")
    page = db.add_page_submission(
        school_id=school.id, fb_page_id="999", page_name="Events",
        added_by_chat_id=7, note="for CS students",
    )
    assert page.status == STATUS_PENDING
    assert db.list_approved_pages() == []
    assert len(db.list_pages(status=STATUS_PENDING)) == 1
    db.approve_page(page.id, "enc-token", "Events Page")
    approved = db.get_page(page.id)
    assert approved is not None and approved.status == STATUS_APPROVED
    assert approved.page_name == "Events Page"
    assert len(db.list_approved_pages()) == 1
    # Duplicate submission for the same school is rejected.
    with pytest.raises(ValueError):
        db.add_page_submission(
            school_id=school.id, fb_page_id="999", page_name="Events",
            added_by_chat_id=7,
        )


def test_subscriptions(db: Database) -> None:
    s1 = db.add_school("Uni A")
    s2 = db.add_school("Uni B")
    db.upsert_user(1, "en")
    db.upsert_user(2, "vi")
    assert db.subscribe(1, s1.id) is True
    assert db.subscribe(1, s1.id) is False  # idempotent
    db.subscribe(1, s2.id)
    db.subscribe(2, s1.id)
    assert {s.id for s in db.user_subscriptions(1)} == {s1.id, s2.id}
    assert db.unsubscribe(1, s2.id) is True
    assert db.unsubscribe(1, s2.id) is False
    # Only active users are returned as subscribers.
    subs = db.subscribers_for_school(s1.id)
    assert {(s.chat_id, s.language) for s in subs} == {(1, "en"), (2, "vi")}
    db.set_user_active(2, False)
    assert [s.chat_id for s in db.subscribers_for_school(s1.id)] == [1]
    # Bulk replace.
    db.set_subscriptions(1, [s2.id])
    assert [s.id for s in db.user_subscriptions(1)] == [s2.id]


def test_seen_posts_dedupe_is_per_page(db: Database) -> None:
    page_id = _school_with_page(db)
    assert not db.has_seen(page_id, "p1")
    db.mark_seen(page_id, "p1")
    assert db.has_seen(page_id, "p1")
    db.mark_seen(page_id, "p1")  # idempotent
    assert not db.has_seen(page_id, "p2")
    assert not db.is_page_initialized(page_id)
    db.mark_page_initialized(page_id)
    assert db.is_page_initialized(page_id)


def test_page_failure_auto_disable(db: Database) -> None:
    page_id = _school_with_page(db)
    for _ in range(MAX_CONSECUTIVE_FAILURES - 1):
        assert db.record_page_failure(page_id, "boom") is False
    assert db.get_page(page_id).status == STATUS_APPROVED
    assert db.record_page_failure(page_id, "boom") is True
    assert db.get_page(page_id).status == STATUS_DISABLED
    assert db.list_approved_pages() == []
    db.record_page_success(page_id)
    assert db.get_page(page_id).consecutive_failures == 0
