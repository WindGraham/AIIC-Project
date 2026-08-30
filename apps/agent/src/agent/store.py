"""SQLite-backed runtime store — accounts / sessions / resumes / bookings.

All runtime data lives on the data disk (``settings.data_dir``, default
``/data/probedesk``), never on ``/``. A single SQLite database holds users,
sessions and user-owned resumes/blookings; live ``InterviewContext`` objects
stay in-memory (``main._CONTEXTS``) because they are transient per live run.

Design: tiny, stdlib-only (``sqlite3``), no ORM. Each table is a thin row
mapping to the domain models in ``main``. Concurrency: a short-lived connection
per call (SQLite handles this fine at this scale).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from .config import get_settings

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resumes (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    resume_text TEXT NOT NULL,
    resume_hash TEXT NOT NULL,
    skills      TEXT NOT NULL DEFAULT '[]',
    is_default  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jds (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    company     TEXT NOT NULL DEFAULT '',
    position    TEXT NOT NULL DEFAULT '',
    jd_text     TEXT NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    resume_id   TEXT NOT NULL DEFAULT '',
    resume_text TEXT NOT NULL DEFAULT '',
    jd_id       TEXT NOT NULL DEFAULT '',
    company     TEXT NOT NULL DEFAULT '',
    position    TEXT NOT NULL DEFAULT '',
    jd_text     TEXT NOT NULL DEFAULT '',
    scheduled_at TEXT NOT NULL,
    notes       TEXT NOT NULL DEFAULT '',
    has_coding  INTEGER NOT NULL DEFAULT 1,
    scenario    TEXT NOT NULL DEFAULT 'algorithm',
    persona     TEXT NOT NULL DEFAULT 'high-peer',
    mode        TEXT NOT NULL DEFAULT 'duplex',
    asap        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    id            TEXT PRIMARY KEY,
    user_id       TEXT NOT NULL,
    interview_id  TEXT NOT NULL,
    position      TEXT NOT NULL DEFAULT '',
    company       TEXT NOT NULL DEFAULT '',
    persona       TEXT NOT NULL DEFAULT 'high-peer',
    overall       REAL NOT NULL DEFAULT 0,
    items_json    TEXT NOT NULL DEFAULT '[]',   -- [{competency,score,evidence,level}]
    missing_json  TEXT NOT NULL DEFAULT '[]',   -- [{slot,why_it_matters,one_line_advice}]
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_resumes_user ON resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_jds_user ON jds(user_id);
CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_interview ON reports(interview_id);
CREATE TABLE IF NOT EXISTS interview_sessions (
    id            TEXT PRIMARY KEY,           -- interview_id
    user_id       TEXT NOT NULL,
    position      TEXT NOT NULL DEFAULT '',
    company       TEXT NOT NULL DEFAULT '',
    transcript_json TEXT NOT NULL DEFAULT '[]', -- [{role,text,ts}]
    recording_url TEXT NOT NULL DEFAULT '',     -- 本地录音/录像文件路径
    started_at    TEXT NOT NULL,
    completed_at  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_isessions_user ON interview_sessions(user_id);
"""

PERSONA_LEVELS = ("peer", "high-peer", "manager")


class Store:
    """Thin SQLite persistence layer (accounts/sessions/resumes/bookings)."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path) if db_path else self._default_path()

    @staticmethod
    def _default_path() -> Path:
        s = get_settings()
        return Path(s.data_dir) / "probedesk.sqlite"

    # -- connection ----------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        self._migrate(conn)
        return conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Additive column migration for DBs created before a field existed."""
        try:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(bookings)").fetchall()}
            if "mode" not in cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN mode TEXT NOT NULL DEFAULT 'duplex'")
            if "asap" not in cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN asap INTEGER NOT NULL DEFAULT 0")
            if "jd_id" not in cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN jd_id TEXT NOT NULL DEFAULT ''")
        except sqlite3.Error:
            pass  # column exists / table missing — nothing to do

    def _now(self) -> datetime:
        return datetime.utcnow()

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _hash_password(password: str, salt: str) -> str:
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()

    # -- users ---------------------------------------------------------------
    def create_user(self, username: str, password: str) -> dict[str, Any]:
        username = (username or "").strip()
        if not username or not password:
            raise ValueError("username and password are required")
        if len(password) < 6:
            raise ValueError("password must be at least 6 characters")
        user_id = str(uuid.uuid4())
        salt = secrets.token_hex(16)
        ph = self._hash_password(password, salt)
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO users(id, username, password_hash, salt, created_at) VALUES(?,?,?,?,?)",
                    (user_id, username, ph, salt, self._now().isoformat()),
                )
        except sqlite3.IntegrityError as e:
            raise ValueError("username already exists") from e
        return {"id": user_id, "username": username}

    def list_user_ids(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT id FROM users").fetchall()
        return [r["id"] for r in rows]

    def verify_user(self, username: str, password: str) -> Optional[dict[str, Any]]:
        username = (username or "").strip()
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if row is None:
            return None
        check = self._hash_password(password, row["salt"])
        if not hmac.compare_digest(check, row["password_hash"]):
            return None
        return {"id": row["id"], "username": row["username"]}

    # -- sessions ------------------------------------------------------------
    def create_session(self, user_id: str, ttl_days: int = 30) -> str:
        token = secrets.token_urlsafe(32)
        expires = (self._now() + timedelta(days=ttl_days)).isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES(?,?,?,?)",
                (token, user_id, self._now().isoformat(), expires),
            )
        return token

    def user_for_session(self, token: str) -> Optional[dict[str, Any]]:
        if not token:
            return None
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE token=?", (token,)).fetchone()
        if row is None:
            return None
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except Exception:
            return None
        if expires < self._now():
            return None
        with self._conn() as conn:
            u = conn.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone()
        if u is None:
            return None
        return {"id": u["id"], "username": u["username"]}

    def delete_session(self, token: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))

    def purge_expired_sessions(self) -> int:
        """Remove expired session rows. Returns the number deleted."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE expires_at < ?", (self._now().isoformat(),))
        return cur.rowcount

    # -- resumes -------------------------------------------------------------
    def list_resumes(self, user_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM resumes WHERE user_id=? ORDER BY is_default DESC, created_at DESC", (user_id,)
            ).fetchall()
        return [self._resume_row(r) for r in rows]

    def get_resume(self, user_id: str, resume_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM resumes WHERE id=? AND user_id=?", (resume_id, user_id)).fetchone()
        return self._resume_row(r) if r else None

    def create_resume(self, user_id: str, name: str, resume_text: str, skills: list[str],
                      is_default: bool = False) -> dict[str, Any]:
        rid = str(uuid.uuid4())
        resume_hash = hashlib.sha256(resume_text.encode("utf-8")).hexdigest()[:16]
        with self._conn() as conn:
            if is_default:
                conn.execute("UPDATE resumes SET is_default=0 WHERE user_id=?", (user_id,))
            conn.execute(
                "INSERT INTO resumes(id, user_id, name, resume_text, resume_hash, skills, is_default, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (rid, user_id, name, resume_text, resume_hash, json.dumps(skills, ensure_ascii=False),
                 1 if is_default else 0, self._now().isoformat()),
            )
        return self.get_resume(user_id, rid)  # type: ignore[return-value]

    def update_resume(self, user_id: str, resume_id: str, *, name: Optional[str] = None,
                      resume_text: Optional[str] = None, skills: Optional[list[str]] = None,
                      is_default: Optional[bool] = None) -> Optional[dict[str, Any]]:
        existing = self.get_resume(user_id, resume_id)
        if existing is None:
            return None
        fields: list[str] = []
        vals: list[Any] = []
        if name is not None:
            fields.append("name=?"); vals.append(name)
        if resume_text is not None:
            fields.append("resume_text=?"); vals.append(resume_text)
            fields.append("resume_hash=?"); vals.append(hashlib.sha256(resume_text.encode("utf-8")).hexdigest()[:16])
        if skills is not None:
            fields.append("skills=?"); vals.append(json.dumps(skills, ensure_ascii=False))
        if is_default is not None:
            with self._conn() as conn:
                if is_default:
                    conn.execute("UPDATE resumes SET is_default=0 WHERE user_id=?", (user_id,))
                conn.execute("UPDATE resumes SET is_default=? WHERE id=? AND user_id=?",
                             (1 if is_default else 0, resume_id, user_id))
            return self.get_resume(user_id, resume_id)
        if fields:
            vals.append(resume_id); vals.append(user_id)
            with self._conn() as conn:
                conn.execute(f"UPDATE resumes SET {', '.join(fields)} WHERE id=? AND user_id=?", vals)
        return self.get_resume(user_id, resume_id)

    def delete_resume(self, user_id: str, resume_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM resumes WHERE id=? AND user_id=?", (resume_id, user_id))
        return cur.rowcount > 0

    @staticmethod
    def _resume_row(r: sqlite3.Row) -> dict[str, Any]:
        try:
            skills = json.loads(r["skills"])
        except Exception:
            skills = []
        return {
            "id": r["id"],
            "user_id": r["user_id"],
            "name": r["name"],
            "resume_text": r["resume_text"],
            "resume_hash": r["resume_hash"],
            "skills": skills,
            "is_default": bool(r["is_default"]),
            "created_at": r["created_at"],
        }

    # -- JDs (company/position/jd_text presets) -------------------------------
    def list_jds(self, user_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jds WHERE user_id=? ORDER BY is_default DESC, created_at DESC", (user_id,)
            ).fetchall()
        return [self._jd_row(r) for r in rows]

    def get_jd(self, user_id: str, jd_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            r = conn.execute("SELECT * FROM jds WHERE id=? AND user_id=?", (jd_id, user_id)).fetchone()
        return self._jd_row(r) if r else None

    def create_jd(self, user_id: str, name: str, company: str, position: str, jd_text: str,
                  is_default: bool = False) -> dict[str, Any]:
        jid = str(uuid.uuid4())
        with self._conn() as conn:
            if is_default:
                conn.execute("UPDATE jds SET is_default=0 WHERE user_id=?", (user_id,))
            conn.execute(
                "INSERT INTO jds(id, user_id, name, company, position, jd_text, is_default, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (jid, user_id, name, company, position, jd_text, 1 if is_default else 0, self._now().isoformat()),
            )
        return self.get_jd(user_id, jid)  # type: ignore[return-value]

    def update_jd(self, user_id: str, jd_id: str, *, name: Optional[str] = None,
                  company: Optional[str] = None, position: Optional[str] = None,
                  jd_text: Optional[str] = None, is_default: Optional[bool] = None) -> Optional[dict[str, Any]]:
        existing = self.get_jd(user_id, jd_id)
        if existing is None:
            return None
        if is_default is True:
            with self._conn() as conn:
                conn.execute("UPDATE jds SET is_default=0 WHERE user_id=?", (user_id,))
        fields, vals = [], []
        if name is not None: fields.append("name=?"); vals.append(name)
        if company is not None: fields.append("company=?"); vals.append(company)
        if position is not None: fields.append("position=?"); vals.append(position)
        if jd_text is not None: fields.append("jd_text=?"); vals.append(jd_text)
        if is_default is not None: fields.append("is_default=?"); vals.append(1 if is_default else 0)
        if fields:
            vals.append(jd_id); vals.append(user_id)
            with self._conn() as conn:
                conn.execute(f"UPDATE jds SET {', '.join(fields)} WHERE id=? AND user_id=?", vals)
        return self.get_jd(user_id, jd_id)

    def delete_jd(self, user_id: str, jd_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM jds WHERE id=? AND user_id=?", (jd_id, user_id))
        return cur.rowcount > 0

    @staticmethod
    def _jd_row(r: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": r["id"],
            "user_id": r["user_id"],
            "name": r["name"],
            "company": r["company"],
            "position": r["position"],
            "jd_text": r["jd_text"],
            "is_default": bool(r["is_default"]),
            "created_at": r["created_at"],
        }

    # -- bookings ------------------------------------------------------------
    def list_bookings(self, user_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM bookings WHERE user_id=? ORDER BY scheduled_at ASC", (user_id,)).fetchall()
        return [self._booking_row(r) for r in rows]

    def get_booking(self, user_id: str, booking_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            b = conn.execute("SELECT * FROM bookings WHERE id=? AND user_id=?", (booking_id, user_id)).fetchone()
        return self._booking_row(b) if b else None

    def save_booking(self, user_id: str, booking: dict[str, Any]) -> dict[str, Any]:
        bid = booking.get("id") or str(uuid.uuid4())
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bookings(id, user_id, name, resume_id, resume_text, jd_id, company, position, "
                "jd_text, scheduled_at, notes, has_coding, scenario, persona, mode, asap, created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bid, user_id, booking.get("name", "模拟面试"), booking.get("resume_id", ""),
                 booking.get("resume_text", ""), booking.get("jd_id", ""), booking.get("company", ""),
                 booking.get("position", ""), booking.get("jd_text", ""),
                 str(booking.get("scheduled_at", self._now().isoformat())),
                 booking.get("notes", ""), 1 if booking.get("has_coding", True) else 0,
                 booking.get("scenario", "algorithm"), booking.get("persona", "high-peer"),
                 booking.get("mode", "duplex"), 1 if booking.get("asap", False) else 0,
                 booking.get("created_at", self._now().isoformat())),
            )
        return self._booking_row(conn.execute("SELECT * FROM bookings WHERE id=? AND user_id=?", (bid, user_id)).fetchone())

    @staticmethod
    def _booking_row(b: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": b["id"],
            "user_id": b["user_id"],
            "name": b["name"],
            "resume_id": b["resume_id"],
            "resume_text": b["resume_text"],
            "jd_id": b["jd_id"] if "jd_id" in b.keys() else "",
            "company": b["company"],
            "position": b["position"],
            "jd_text": b["jd_text"],
            "scheduled_at": b["scheduled_at"],
            "notes": b["notes"],
            "has_coding": bool(b["has_coding"]),
            "scenario": b["scenario"],
            "persona": b["persona"],
            "mode": b["mode"] if "mode" in b.keys() else "duplex",
            "asap": bool(b["asap"]) if "asap" in b.keys() else False,
            "created_at": b["created_at"],
        }

    # -- reports (cross-field memory / learning curve) ------------------------
    def save_report(self, user_id: str, interview_id: str, *, position: str, company: str,
                    persona: str, overall: float, items: list[dict], missing: list[dict]) -> None:
        """Persist a finished interview result (C2). Upserts by interview_id so
        re-reading /report never duplicates a row."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO reports(id, user_id, interview_id, position, company, persona, "
                "overall, items_json, missing_json, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("rpt-" + interview_id, user_id, interview_id, position or "", company or "",
                 persona or "high-peer", float(overall or 0),
                 json.dumps(items, ensure_ascii=False), json.dumps(missing, ensure_ascii=False),
                 self._now().isoformat()),
            )

    def list_reports(self, user_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """Past interview results, newest first (drives learning-curve trends)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM reports WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit)
            ).fetchall()
        out = []
        for r in rows:
            try:
                items = json.loads(r["items_json"])
            except Exception:
                items = []
            try:
                missing = json.loads(r["missing_json"])
            except Exception:
                missing = []
            out.append({
                "id": r["id"],
                "interview_id": r["interview_id"],
                "position": r["position"],
                "company": r["company"],
                "persona": r["persona"],
                "overall": r["overall"],
                "items": items,
                "missing": missing,
                "created_at": r["created_at"],
            })
        return out

    # -- interview sessions (full transcript + recording, "全部存成数据") --------
    def save_session_transcript(self, user_id: str, interview_id: str, *, position: str,
                                company: str, transcript: list[dict]) -> None:
        """Persist the full conversation transcript for an interview (upsert by id)."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO interview_sessions(id, user_id, position, company, transcript_json, started_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET transcript_json=excluded.transcript_json, "
                "user_id=excluded.user_id, position=excluded.position, company=excluded.company",
                (interview_id, user_id, position or "", company or "",
                 json.dumps(transcript, ensure_ascii=False), self._now().isoformat()),
            )

    def set_session_recording(self, user_id: str, interview_id: str, recording_url: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE interview_sessions SET recording_url=? WHERE id=? AND user_id=?",
                (recording_url, interview_id, user_id),
            )

    def get_session(self, user_id: str, interview_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as conn:
            r = conn.execute(
                "SELECT * FROM interview_sessions WHERE id=? AND user_id=?", (interview_id, user_id)
            ).fetchone()
        if r is None:
            return None
        try:
            transcript = json.loads(r["transcript_json"])
        except Exception:
            transcript = []
        return {"id": r["id"], "position": r["position"], "company": r["company"],
                "transcript": transcript, "recording_url": r["recording_url"],
                "started_at": r["started_at"]}


# --- module-level singleton (settings-driven) --------------------------------
_store: Optional[Store] = None


def get_store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
