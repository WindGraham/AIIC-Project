"""Tests for the SQLite store: accounts / sessions / resumes / bookings.

Run: cd apps/agent && PYTHONPATH=src .venv/bin/python -m pytest src/agent/test_store.py -q
"""

import os
import tempfile

import pytest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="probedesk_test_"))

from agent.store import Store, get_store  # noqa: E402


@pytest.fixture()
def store():
    d = tempfile.mkdtemp(prefix="probedesk_store_")
    return Store(d.__add__("/probedesk-test.sqlite"))


def test_create_and_verify_user(store):
    u = store.create_user("alice", "secret123")
    assert u["username"] == "alice"
    assert store.verify_user("alice", "secret123")["username"] == "alice"
    assert store.verify_user("alice", "wrong") is None
    assert store.verify_user("nobody", "secret123") is None


def test_duplicate_user_rejected(store):
    store.create_user("bob", "secret123")
    with pytest.raises(ValueError):
        store.create_user("bob", "secret123")


def test_password_too_short(store):
    with pytest.raises(ValueError):
        store.create_user("x", "123")


def test_session_roundtrip(store):
    u = store.create_user("carol", "secret123")
    token = store.create_session(u["id"])
    assert store.user_for_session(token) is not None
    store.delete_session(token)
    assert store.user_for_session(token) is None


def test_session_invalid_token(store):
    assert store.user_for_session("bogus") is None
    assert store.user_for_session("") is None


def test_resume_crud(store):
    u = store.create_user("dave", "secret123")
    r = store.create_resume(u["id"], "简历A", "python 后端", ["Python", "Go"], is_default=True)
    assert r["is_default"] is True
    # second default flips the first
    r2 = store.create_resume(u["id"], "简历B", "算法", ["C++"], is_default=True)
    assert store.get_resume(u["id"], r["id"])["is_default"] is False
    assert store.get_resume(u["id"], r2["id"])["is_default"] is True

    assert len(store.list_resumes(u["id"])) == 2
    upd = store.update_resume(u["id"], r2["id"], name="简历B2", skills=["C++", "STL"])
    assert upd["name"] == "简历B2"
    assert upd["skills"] == ["C++", "STL"]

    assert store.delete_resume(u["id"], r["id"]) is True
    assert store.delete_resume(u["id"], r["id"]) is False
    assert len(store.list_resumes(u["id"])) == 1


def test_resume_is_user_scoped(store):
    u1 = store.create_user("u1", "secret123")
    u2 = store.create_user("u2", "secret123")
    r = store.create_resume(u1["id"], "简历", "text", [])
    assert store.get_resume(u2["id"], r["id"]) is None


def test_booking_roundtrip(store):
    u = store.create_user("erin", "secret123")
    b = store.save_booking(u["id"], {
        "name": "字节面", "company": "字节跳动", "position": "后端", "jd_text": "jd",
        "has_coding": True, "scenario": "algorithm", "persona": "manager",
    })
    assert b["persona"] == "manager"
    assert b["has_coding"] is True
    got = store.get_booking(u["id"], b["id"])
    assert got["company"] == "字节跳动"
    # user-scoped read
    u2 = store.create_user("erin2", "secret123")
    assert store.get_booking(u2["id"], b["id"]) is None
    assert len(store.list_bookings(u["id"])) == 1
