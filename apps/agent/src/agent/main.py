"""Phase-0 minimal FastAPI app: health + booking/interview CRUD over an
in-memory repo (the "agent API is the single source of truth" light path).
Live interviewer logic (prep/live/post + voice) is layered on in later phases."""

import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket
from pydantic import BaseModel, Field

from .config import get_settings
from .store import PERSONA_LEVELS, get_store

# Interview modes selectable at booking: text chat / push-to-talk / full-duplex.
MODES = ("text", "ptt", "duplex")
# 面试官严格程度 (relaxed/standard/strict).
STRICTNESS_LEVELS = ("relaxed", "standard", "strict")
# 预约制上架下限：预约时间必须至少在当前时间之后这么多分钟（业务规则）。
MIN_BOOKING_AHEAD_MIN = 30
from .contracts import InterviewContext
from .coding import judge_code, load_problem
from .llm import LLM
from .pipeline import ask_current, current_question, finalize, record_answer
from .prep import build_plan
from .liveflow import LiveFlow
from .stt import transcribe_flash
from .tts import synthesize
from .voice_ws import voice_ws_handler
from .livekit_bridge import (
    agent_join as livekit_agent_join,
    agent_leave as livekit_agent_leave,
    livekit_configured,
    room_status as livekit_room_status,
)

app = FastAPI(title="aiic-agent", version="0.1.0")
logger = logging.getLogger("agent.main")

# in-memory contexts keyed by interview id (transient per live run)
_CONTEXTS: dict[str, InterviewContext] = {}
# per-interview live interviewer flow (time-aware, per-round agent). Created lazily
# when a live turn first happens, keyed by the same interview id.
_FLOWS: dict[str, LiveFlow] = {}
_MAX_CONTEXTS = 500  # guard against unbounded memory growth from unauthed prep
# Background prep executor + pending set: /start returns immediately with a
# "preparing" state while build_plan (search + LLM) runs in a worker thread.
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

_PREP_EXECUTOR = ThreadPoolExecutor(max_workers=2)
_PENDING: set[str] = set()
# interview_id -> set when build_plan failed. Drives the "red light" (cannot start).
_FAILED: set[str] = set()
# interview_id -> owner user_id, set at /start. Used to gate the live interview
# endpoints & /report persistence to the interviewer's owner (cross-user safety).
_OWNER: dict[str, str] = {}
# booking_id -> interview_id, so the booking list can show each interview's prep status.
_BOOKING_TO_INTERVIEW: dict[str, str] = {}
# interview_id -> booking-derived live config (has_coding/notes/scenario/persona),
# captured at /start so the flow uses the right structure (e.g. skip coding round).
_BOOKING_CFG: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Domain models (booking -> interview). Full InterviewContext lives in
# contracts.InterviewContext and is produced by the prep phase.
# ---------------------------------------------------------------------------
class Booking(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "模拟面试"
    resume_id: str = ""
    resume_text: str = ""
    jd_id: str = ""              # 关联的预设置岗位 JD（公司/岗位/JD 一键带入）
    company: str = ""
    position: str = ""
    jd_text: str = ""
    scheduled_at: datetime = Field(default_factory=datetime.utcnow)
    notes: str = ""
    has_coding: bool = True
    scenario: str = "algorithm"  # algorithm | retest(保研复试占位)
    persona: str = "high-peer"   # peer | high-peer | manager
    strictness: str = "standard" # relaxed | standard | strict (面试官严格程度)
    mode: str = "duplex"         # text | ptt | duplex (面试方案)
    asap: bool = False           # 尽快开始：后台准备完毕即可答题，不受预约时间限制
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Interview(BaseModel):
    id: str
    booking_id: str
    room_name: str
    status: str = "scheduled"  # scheduled -> open -> live -> completed
    scheduled_at: datetime
    context_id: Optional[str] = None
    # after the interview
    recording_url: Optional[str] = None
    report_json: Optional[str] = None
    share_token: Optional[str] = None


# ---------------------------------------------------------------------------
# In-memory contexts keyed by interview id (transient per live run).
# Persistent user/session/resume/booking data lives in SQLite on the data disk
# (apps/agent/src/agent/store.py -> settings.data_dir = /data/probedesk).
# ---------------------------------------------------------------------------
def _put_context(iid: str, ctx: InterviewContext) -> None:
    """Store a live context, evicting the oldest once the cap is exceeded."""
    if len(_CONTEXTS) >= _MAX_CONTEXTS:
        try:
            _CONTEXTS.pop(next(iter(_CONTEXTS)), None)
        except StopIteration:
            pass
    _CONTEXTS[iid] = ctx


def _history_brief(user_id: str, position: str, limit: int = 6) -> str:
    """C2 cross-field memory: a short brief of the user's past weak points so the
    next interviewer plan targets them (the 'learning curve' signal). Empty if none."""
    try:
        reports = get_store().list_reports(user_id, limit=limit)
    except Exception:
        return ""
    if not reports:
        return ""
    lines = []
    # most recent weak competencies (low scores) + missing slots
    weak: list[str] = []
    slots: list[str] = []
    for r in reports:
        for it in r.get("items", []):
            if float(it.get("score", 5)) < 3 and it.get("competency") not in weak:
                weak.append(it.get("competency", ""))
        for m in r.get("missing", []):
            if m.get("slot") and m.get("slot") not in slots:
                slots.append(m.get("slot", ""))
    if weak:
        lines.append("过去薄弱项：" + "、".join(x for x in weak[:4] if x))
    if slots:
        lines.append("上次追问未答好：" + "、".join(x for x in slots[:4] if x))
    if not lines:
        return ""
    return "（跨场记忆）" + "；".join(lines) + "。请在本场更有针对性地考察并引导这些点。"


@app.on_event("startup")
def _startup():
    """Opportunistic hygiene on boot: drop expired sessions + seed default resume/JD
    for any existing user that doesn't have one yet (so older accounts get them too)."""
    try:
        get_store().purge_expired_sessions()
    except Exception:
        pass
    try:
        for uid in get_store().list_user_ids():
            seed_defaults_for_user(uid)
    except Exception:  # noqa: BLE001
        pass


def _auth_user(authorization: str = Header(default="")) -> dict[str, Any]:
    """Bearer-token auth -> current user, or 401."""
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    user = get_store().user_for_session(token) if token else None
    if user is None:
        raise HTTPException(401, "not authenticated")
    return user


def _optional_user(authorization: str = Header(default="")) -> Optional[dict[str, Any]]:
    """Like _auth_user but returns None when unauthenticated (never raises)."""
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    return get_store().user_for_session(token) if token else None


@app.get("/health")
def health():
    s = get_settings()
    return {
        "status": "ok",
        "app_env": s.app_env,
        "llm": {"configured": bool(s.llm_api_key), "model": s.llm_model},
        "vision": {"configured": bool(s.gemini_api_key), "model": s.gemini_model},
        "stt": {"configured": bool(s.volcengine_api_key), "resource_id": s.volcengine_asr_resource_id},
        "tts": {"configured": bool(s.minimax_api_key), "model": s.minimax_tts_model},
        "livekit": {"url": s.livekit_url, "configured": bool(s.livekit_api_key)},
        "search": {"xhs": bool(s.xhs_cookie), "zhihu": bool(s.zhihu_d_cookie)},
    }


@app.post("/api/interviews/book", response_model=Booking, status_code=201)
def book_interview(payload: Booking, user: dict = Depends(_auth_user)):
    # Server-owned id: never trust a client-supplied id (prevents cross-user
    # overwrite via INSERT OR REPLACE on a guessed/observed booking id).
    payload.id = str(uuid.uuid4())
    store = get_store()
    # 若选择了预设置的岗位 JD，一键带入 公司/岗位/JD 文本。
    if payload.jd_id:
        jd = store.get_jd(user["id"], payload.jd_id)
        if jd:
            payload.company = payload.company or jd.get("company", "")
            payload.position = payload.position or jd.get("position", "")
            payload.jd_text = jd.get("jd_text", "")
    # 若选择了预设置的简历，一键带入简历文本。
    if payload.resume_id:
        r = store.get_resume(user["id"], payload.resume_id)
        if r:
            payload.resume_text = r.get("resume_text", "")
    # Validate persona against the allow-list (block prompt-injection into the
    # interviewer-planning LLM via the persona field).
    if payload.persona not in PERSONA_LEVELS:
        payload.persona = "high-peer"
    # Validate interview mode (text | ptt | duplex).
    if payload.mode not in MODES:
        payload.mode = "duplex"
    if payload.strictness not in STRICTNESS_LEVELS:
        payload.strictness = "standard"
    if not payload.name:
        payload.name = f"{payload.position or '模拟'}面试"
    # 尽快开始 (asap): allowed at any time; the agent answers as soon as prep done.
    # 预约制: scheduled_at must be >= now + MIN_BOOKING_AHEAD_MIN (business rule).
    if not payload.asap:
        dt = payload.scheduled_at
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        now = datetime.utcnow()
        if (dt - now).total_seconds() < MIN_BOOKING_AHEAD_MIN * 60:
            raise HTTPException(400, f"预约时间需至少在当前时间之后 {MIN_BOOKING_AHEAD_MIN} 分钟")
    store.save_booking(user["id"], payload.model_dump())
    return payload


@app.get("/api/interviews")
def list_interviews(user: dict = Depends(_auth_user)):
    out = []
    now = datetime.utcnow()
    for b in get_store().list_bookings(user["id"]):
        scheduled = b.get("scheduled_at")
        try:
            # scheduled_at is stored as ISO; may be tz-aware or naive. Normalize.
            dt = datetime.fromisoformat(str(scheduled))
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            delta = (dt - now).total_seconds()
        except Exception:
            delta = 0
        iid = _BOOKING_TO_INTERVIEW.get(b.get("id"))
        prep = "not_started"  # 还没点"进入面试"，后台还没开始准备
        if iid:
            prep = _prep_status(iid)  # preparing | ready | failed
        out.append({
            **b,
            "seconds_until_start": int(max(0, delta)),
            "status": "available" if delta <= 0 else "scheduled",
            "asap": bool(b.get("asap", False)),
            "gate": bool(b.get("asap", False)) or delta <= 0,
            "prep": prep,
            "interview_id": iid,
        })
    out.sort(key=lambda x: x.get("scheduled_at", ""))
    return out


@app.post("/api/interviews/{booking_id}/start", status_code=202)
def start_interview(booking_id: str, user: dict = Depends(_auth_user)):
    b = get_store().get_booking(user["id"], booking_id)
    if b is None:
        raise HTTPException(404, "booking not found")
    iid = str(uuid.uuid4())
    _BOOKING_TO_INTERVIEW[booking_id] = iid
    persona = b.get("persona", "high-peer") if b.get("persona") in PERSONA_LEVELS else "high-peer"
    _PENDING.add(iid)
    _OWNER[iid] = user["id"]
    sched = b.get("scheduled_at", "")
    try:
        sdt = datetime.fromisoformat(str(sched))
        if sdt.tzinfo is not None:
            sdt = sdt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        sdt = datetime.utcnow()
    _BOOKING_CFG[iid] = {
        "has_coding": bool(b.get("has_coding", True)),
        "notes": b.get("notes", ""),
        "scenario": b.get("scenario", "algorithm"),
        "persona": persona,
        "strictness": b.get("strictness", "standard") if b.get("strictness") in STRICTNESS_LEVELS else "standard",
        "scheduled_at": sdt,
        "asap": bool(b.get("asap", False)),
    }

    def _do_start():
        """Run build_plan (search + LLM) in a worker; store the context when done.
        On failure, mark the interview as failed (red light) so the UI can surface
        a 'cannot start' state instead of a silent 404."""
        try:
            persona_inner = b.get("persona", "high-peer") if b.get("persona") in PERSONA_LEVELS else "high-peer"
            ctx = build_plan(b.get("resume_text", ""), b.get("jd_text", ""), b.get("company", ""),
                             b.get("position", ""), "mid", "zh", persona=persona_inner,
                             memory_brief=_history_brief(user["id"], b.get("position", "")))
            _put_context(iid, ctx)
            _FAILED.discard(iid)
        except Exception as exc:  # noqa: BLE001
            logger.exception("prep failed for %s: %s", booking_id, exc)
            _FAILED.add(iid)
        finally:
            _PENDING.discard(iid)

    _PREP_EXECUTOR.submit(_do_start)
    # Answer-ready only when context is built; the room polls /next meanwhile.
    ctx = _CONTEXTS.get(iid)
    return {
        "interview_id": iid,
        "booking_id": booking_id,
        "status": "preparing" if ctx is None else "ready",
        "question": ask_current(ctx) if ctx else None,
        "persona": persona,
        "asap": b.get("asap", False),
        "gate": _can_start_now(iid),
        "plan": None if ctx is None else {
            "sections_order": ctx.plan.sections_order,
            "questions": [{"id": q.id, "section": q.section, "text": q.text,
                           "difficulty": q.difficulty, "problem_id": q.problem_id} for q in ctx.plan.questions],
        },
    }


# ---------------------------------------------------------------------------
# Auth + resume management (login capability). Accounts/sessions/resumes live
# in SQLite on the data disk.
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/register", status_code=201)
def register(req: RegisterRequest):
    try:
        user = get_store().create_user(req.username, req.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    seed_defaults_for_user(user["id"])
    token = get_store().create_session(user["id"])
    return {"user": user, "token": token}


def seed_defaults_for_user(user_id: str) -> None:
    """给新注册用户"默认拥有"一份脱敏简历 + 一份岗位 JD（从 docs 样例读入）。

    仅当用户还没有任何简历/JD 时才创建，且第一条设为默认；用户可自行增删改。
    """
    try:
        # docs/ lives at the repo root (parents[4] from this file).
        docdir = Path(__file__).resolve().parents[4] / "docs"
        resume_file = docdir / "简历样例-脱敏.md"
        jd_file = docdir / "JD样例-脱敏.md"
        resume_text = resume_file.read_text(encoding="utf-8") if resume_file.exists() else ""
        jd_text = jd_file.read_text(encoding="utf-8") if jd_file.exists() else ""
        store = get_store()
        # 脱敏样例简历
        if resume_text.strip():
            existing_resumes = store.list_resumes(user_id)
            if not existing_resumes:
                store.create_resume(user_id, "默认简历（样例）", resume_text, ["C++", "Python", "Go", "LLM"], is_default=True)
        # 脱敏样例 JD
        if jd_text.strip():
            existing_jds = store.list_jds(user_id)
            if not existing_jds:
                store.create_jd(user_id, "默认岗位（样例）", "某互联网大厂", "AI 应用开发实习生", jd_text, is_default=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("seed_defaults_for_user failed: %s", exc)


@app.post("/api/auth/login")
def login(req: LoginRequest):
    user = get_store().verify_user(req.username, req.password)
    if user is None:
        raise HTTPException(401, "invalid username or password")
    token = get_store().create_session(user["id"])
    return {"user": user, "token": token}


@app.post("/api/auth/logout")
def logout(authorization: str = Header(default="")):
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if token:
        get_store().delete_session(token)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(_auth_user)):
    return {"user": user}


# --- resumes ----------------------------------------------------------------
class ResumeIn(BaseModel):
    name: str = "我的简历"
    resume_text: str
    skills: list[str] = []
    is_default: bool = False


@app.post("/api/parse/resume")
def parse_resume(req: dict):
    """Decode an uploaded resume file (pdf/docx/md/txt/xlsx) to plain text.

    The browser sends the file bytes as base64 (single in-memory request), the
    agent decodes them offline and returns the extracted text so the web page can
    populate the resume_text field. No LLM call involved. Declared as a sync `def`
    so FastAPI runs file I/O + parsing in a worker thread (does not block the loop).
    """
    import base64 as _b64

    b64 = str(req.get("data", ""))
    filename = str(req.get("filename", ""))
    if not b64:
        raise HTTPException(400, "no file data")
    try:
        raw = _b64.b64decode(b64, validate=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid base64 payload")
    if len(raw) > 20 * 1024 * 1024:  # 20 MB cap
        raise HTTPException(413, "file too large (max 20 MB)")
    from .resume_parse import decode_resume  # noqa: PLC0415

    result = decode_resume(raw, filename)
    if result["error"]:
        logger.warning("parse/resume error: %s", result["error"])
    return {"text": result["text"], "format": result["format"], "error": result["error"]}


@app.get("/api/resumes")
def list_resumes(user: dict = Depends(_auth_user)):
    return get_store().list_resumes(user["id"])


@app.post("/api/resumes", status_code=201)
def create_resume(req: ResumeIn, user: dict = Depends(_auth_user)):
    if not req.resume_text.strip():
        raise HTTPException(400, "resume_text is required")
    return get_store().create_resume(user["id"], req.name, req.resume_text, req.skills, req.is_default)


@app.put("/api/resumes/{resume_id}")
def update_resume(resume_id: str, req: ResumeIn, user: dict = Depends(_auth_user)):
    got = get_store().update_resume(user["id"], resume_id, name=req.name, resume_text=req.resume_text,
                                    skills=req.skills, is_default=req.is_default)
    if got is None:
        raise HTTPException(404, "resume not found")
    return got


@app.delete("/api/resumes/{resume_id}")
def delete_resume(resume_id: str, user: dict = Depends(_auth_user)):
    if not get_store().delete_resume(user["id"], resume_id):
        raise HTTPException(404, "resume not found")
    return {"ok": True}


# --- 岗位 JD 管理（可提前设置，预约时选择；每人可设默认） ---------------
class JDIn(BaseModel):
    name: str = "我的岗位JD"
    company: str = ""
    position: str = ""
    jd_text: str
    is_default: bool = False


@app.get("/api/jds")
def list_jds(user: dict = Depends(_auth_user)):
    return get_store().list_jds(user["id"])


@app.post("/api/jds", status_code=201)
def create_jd(req: JDIn, user: dict = Depends(_auth_user)):
    if not req.jd_text.strip():
        raise HTTPException(400, "jd_text is required")
    return get_store().create_jd(user["id"], req.name, req.company, req.position, req.jd_text, req.is_default)


@app.put("/api/jds/{jd_id}")
def update_jd(jd_id: str, req: JDIn, user: dict = Depends(_auth_user)):
    got = get_store().update_jd(user["id"], jd_id, name=req.name, company=req.company,
                                position=req.position, jd_text=req.jd_text, is_default=req.is_default)
    if got is None:
        raise HTTPException(404, "jd not found")
    return got


@app.delete("/api/jds/{jd_id}")
def delete_jd(jd_id: str, user: dict = Depends(_auth_user)):
    if not get_store().delete_jd(user["id"], jd_id):
        raise HTTPException(404, "jd not found")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Interview brain over HTTP (Phase-2 glue). Contexts stored in memory keyed by id.
# ---------------------------------------------------------------------------
class PrepareRequest(BaseModel):
    resume_text: str
    jd_text: str
    company: str
    position: str
    seniority: str = "mid"
    lang: str = "zh"


@app.post("/api/interviews/prepare", status_code=201)
def prepare(req: PrepareRequest):
    interview_id = str(uuid.uuid4())
    ctx = build_plan(req.resume_text, req.jd_text, req.company, req.position, req.seniority, req.lang)
    _put_context(interview_id, ctx)
    return {
        "interview_id": interview_id,
        "question": ask_current(ctx),
        "plan": {
            "sections_order": ctx.plan.sections_order,
            "questions": [{"id": q.id, "section": q.section, "text": q.text, "difficulty": q.difficulty,
                           "problem_id": q.problem_id} for q in ctx.plan.questions],
        },
    }


def _can_start_now(interview_id: str) -> bool:
    """Whether the agent is ALLOWED to answer now.

    - 尽快开始 (asap): True once prep is done (scheduled time ignored).
    - 预约制: True only when now >= scheduled_at.
    """
    cfg = _BOOKING_CFG.get(interview_id, {})
    if cfg.get("asap"):
        return True
    sched = cfg.get("scheduled_at")
    if sched is None:
        return True
    try:
        dt = sched if sched.tzinfo is None else sched.astimezone(timezone.utc).replace(tzinfo=None)
        return datetime.utcnow() >= dt
    except Exception:
        return True


def _prep_status(interview_id: str) -> str:
    """Prep light: 'preparing' (yellow) | 'ready' (green) | 'failed' (red)."""
    if interview_id in _FAILED:
        return "failed"
    if interview_id in _PENDING:
        return "preparing"
    if interview_id in _CONTEXTS:
        return "ready"
    # Unknown interview id: treat as not found.
    return "preparing"


def _ctx(interview_id: str) -> tuple[Optional[InterviewContext], bool]:
    """(context, is_preparing). We treat iid missing from _PENDING as a hard 404."""
    ctx = _CONTEXTS.get(interview_id)
    if ctx is not None:
        return ctx, False
    if interview_id in _FAILED:
        raise HTTPException(409, "interview preparation failed")
    if interview_id in _PENDING:
        return None, True
    raise HTTPException(404, "interview not prepared")


def _require_ctx(interview_id: str) -> InterviewContext:
    """Like _ctx but raises 409 (preparing) instead of returning a 2-tuple."""
    ctx, preparing = _ctx(interview_id)
    if preparing:
        raise HTTPException(409, "interview still preparing — try again shortly")
    assert ctx is not None
    return ctx


def _flow_for(interview_id: str, *, has_coding: bool | None = None, notes: str | None = None,
              scenario: str | None = None, group_min: int | None = None,
              coding_min: int | None = None) -> LiveFlow:
    """Lazily create (once) the per-interview LiveFlow and cache it.

    Booking-derived config (captured at /start) is preferred; explicit args override.
    """
    flow = _FLOWS.get(interview_id)
    if flow is None:
        ctx = _require_ctx(interview_id)
        cfg = _BOOKING_CFG.get(interview_id, {})
        flow = LiveFlow(
            ctx,
            has_coding=has_coding if has_coding is not None else bool(cfg.get("has_coding", True)),
            notes=notes if notes is not None else str(cfg.get("notes", "")),
            scenario=scenario if scenario is not None else str(cfg.get("scenario", "algorithm")),
            group_min=group_min if group_min is not None else 40,
            coding_min=coding_min if coding_min is not None else 20,
            strictness=str(cfg.get("strictness", "standard")),
        )
        # Ensure the persona in the context matches what the user chose at booking.
        persona = cfg.get("persona")
        if persona and persona in PERSONA_LEVELS:
            flow.ctx.persona = persona
        _FLOWS[interview_id] = flow
    return flow


def _check_owner(interview_id: str, user: Optional[dict[str, Any]] = None) -> None:
    """Raise 403 if the interview has a recorded owner and the caller isn't it.

    Best-effort cross-user guard: interviews created via /start record an owner;
    anonymous/legacy prep-created interviews have none (public-by-id, e.g. /share).
    """
    owner = _OWNER.get(interview_id)
    if owner and (user is None or user.get("id") != owner):
        raise HTTPException(403, "not your interview")


@app.get("/api/interviews/{interview_id}/next")
def next_question(interview_id: str, user: Optional[dict] = Depends(_optional_user)):
    _check_owner(interview_id, user)
    status = _prep_status(interview_id)
    if status == "failed":
        return {"status": "failed", "question": None, "done": False, "section": None, "gate": False}
    ctx, preparing = _ctx(interview_id)
    if preparing:
        return {"status": "preparing", "question": None, "done": False, "section": None, "gate": False}
    # 预约制：时间未到，agent 暂不回复（门控）。
    if not _can_start_now(interview_id):
        return {"status": "ready", "gate": False, "question": None, "done": False,
                "section": None, "state_label": "未到预约时间，暂不能答题", "state": None}
    # Every live interview is driven by the per-round LiveFlow agent.
    flow = _flow_for(interview_id)
    opening = flow.opening_line()  # idempotent
    return {
        "question": opening,
        "done": flow.done,
        "section": flow.section_for_ui(),
        "phase": flow.phase,
        "state": flow.state,
        "state_label": flow.state_label(),
        "gate": True,
        "liveflow": True,
    }


@app.post("/api/interviews/{interview_id}/answer")
def answer(interview_id: str, req: dict, user: dict = Depends(_auth_user)):
    _check_owner(interview_id, user)
    _require_ctx(interview_id)
    # 预约制：时间未到，agent 不回复（不推进流程）。
    if not _can_start_now(interview_id):
        return {"gated": True, "next_question": None, "done": False, "section": None,
                "state": None, "state_label": "未到预约时间，暂不能答题"}
    txt = str(req.get("answer", "")).strip()
    flow = _flow_for(interview_id)
    if not txt:
        # No text yet: (re)seed the opening question.
        opening = flow.opening_line()
        return {"next_question": opening, "done": flow.done, "section": flow.section_for_ui(),
                "phase": flow.phase, "state": flow.state, "state_label": flow.state_label()}
    if not flow.opened:
        # The candidate answered before the agent spoke (defensive): open first,
        # then treat the text as this first answer.
        flow.opening_line()
    nxt = flow.next_line(txt)
    return {"next_question": nxt, "done": flow.done, "section": flow.section_for_ui(),
            "phase": flow.phase, "state": flow.state, "state_label": flow.state_label()}


@app.get("/api/interviews/{interview_id}/report")
def report(interview_id: str, user: Optional[dict] = Depends(_optional_user)):
    ctx = _require_ctx(interview_id)
    sc = finalize(ctx)
    os_ = sc.interviewer_os
    result = {
        "overall": sc.overall,
        "items": [s.model_dump() for s in sc.items],
        "summary": sc.summary,
        "next_steps": sc.next_steps,
        "interviewer_os": {
            "hidden_concern": os_.hidden_concern,
            "missing_slots": [{"slot": m.slot, "evidence": m.evidence, "why_it_matters": m.why_it_matters,
                               "what_i_want_to_hear": m.what_i_want_to_hear, "one_line_advice": m.one_line_advice}
                              for m in os_.missing_slots],
        },
    }
    # C2: persist the result so future interviews reuse the weak points — but
    # ONLY when the caller is the interview's owner (no cross-user memory leak).
    if user is not None and (interview_id not in _OWNER or _OWNER[interview_id] == user["id"]):
        try:
            get_store().save_report(
                user["id"], interview_id,
                position=ctx.job.position, company=ctx.job.company, persona=getattr(ctx, "persona", "high-peer"),
                overall=sc.overall,
                items=[s.model_dump() for s in sc.items],
                missing=[{"slot": m.slot, "why_it_matters": m.why_it_matters,
                          "one_line_advice": m.one_line_advice} for m in os_.missing_slots],
            )
        except Exception:
            pass
    return result


@app.get("/api/interviews/history")
def history(user: dict = Depends(_auth_user)):
    """Cross-field memory: past interview results for the learning curve (C2)."""
    return get_store().list_reports(user["id"])


@app.post("/api/interviews/{interview_id}/screen-note")
def screen_note(interview_id: str, req: dict, user: dict = Depends(_auth_user)):
    """Candidate 开摄像头/共享屏时，前端把 Gemini 读到的屏幕文本实时喂给 agent。

    Stored on the LiveFlow's `screen_note` and included in the per-round agent prompt
    as a '看屏幕' 旁注, so the interviewer can react to what's on the screen.
    """
    _check_owner(interview_id, user)
    flow = _flow_for(interview_id)
    text = str(req.get("text", "")).strip()
    if text:
        # 前端已用 Gemini/Kimi 把屏幕帧读成文字，这里直接累积成"看屏幕"旁注。
        flow.add_screen_note(text[:400])
    return {"ok": True}


RECORDINGS_DIR = Path(get_settings().data_dir) / "recordings"


@app.post("/api/interviews/{interview_id}/save-transcript")
def save_interview_transcript(interview_id: str, req: dict, user: dict = Depends(_auth_user)):
    """Persist the full conversation transcript (user voice→text, agent reply) for an
    interview. 前端在面试中对每一轮实时上报，保证"全部交互数据"落库。"""
    _check_owner(interview_id, user)
    ctx = _require_ctx(interview_id)
    items = req.get("items") if isinstance(req.get("items"), list) else []
    transcript = [{"role": str(it.get("role", "")), "text": str(it.get("text", "")),
                   "ts": str(it.get("ts", ""))} for it in items if isinstance(it, dict)]
    get_store().save_session_transcript(user["id"], interview_id,
                                        position=ctx.job.position, company=ctx.job.company,
                                        transcript=transcript)
    return {"ok": True}


@app.post("/api/interviews/{interview_id}/recording")
def upload_interview_recording(interview_id: str, req: dict, user: dict = Depends(_auth_user)):
    """Save a browser-recorded audio/video blob (base64) to the data disk and record
    its path, so the user's voice/camera/screen are preserved as data."""
    _check_owner(interview_id, user)
    import base64 as _b64

    data = str(req.get("data", ""))
    mime = str(req.get("mime", "video/webm"))
    if not data:
        raise HTTPException(400, "no recording data")
    try:
        raw = _b64.b64decode(data, validate=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "invalid base64")
    if len(raw) > 200 * 1024 * 1024:  # 200 MB cap
        raise HTTPException(413, "recording too large (max 200 MB)")
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in interview_id if c.isalnum() or c in "-_") or "interview"
    ext = ".webm" if "webm" in mime else ".webm"
    fname = f"{safe}-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}{ext}"
    path = RECORDINGS_DIR / fname
    path.write_bytes(raw)
    url = f"/recordings/{fname}"
    get_store().set_session_recording(user["id"], interview_id, url)
    return {"ok": True, "url": url, "bytes": len(raw)}


# ---------------------------------------------------------------------------
# Voice (PTT) endpoints — Volcengine STT + MiniMax TTS
# ---------------------------------------------------------------------------
class TTSCall(BaseModel):
    text: str
    voice: str | None = None


class STTCall(BaseModel):
    audio_b64: str
    format: str = "wav"
    mime: str | None = None


class VoiceAnswer(BaseModel):
    interview_id: str
    audio_b64: str = ""
    format: str = "wav"
    mime: str | None = None


@app.post("/api/voice/tts")
def voice_tts(req: TTSCall):
    mp3 = synthesize(req.text, req.voice)
    return {"audio_b64": base64.b64encode(mp3).decode(), "bytes": len(mp3)}


@app.post("/api/voice/stt")
def voice_stt(req: STTCall):
    from .stt import transcribe_audio
    return {"text": transcribe_audio(req.audio_b64, req.mime)}


@app.post("/api/voice/answer")
def voice_answer(req: VoiceAnswer, user: dict = Depends(_auth_user)):
    _check_owner(req.interview_id, user)
    _require_ctx(req.interview_id)
    # 预约制：时间未到，agent 不回复。
    if not _can_start_now(req.interview_id):
        speak = "未到预约时间，暂不能答题。请到预约时间后再开始。"
        mp3 = synthesize(speak)
        return {"text": "", "spoken": speak, "next_question": speak, "done": False,
                "audio_b64": base64.b64encode(mp3).decode(), "section": None, "phase": None,
                "gated": True}
    flow = _flow_for(req.interview_id)
    # When the AI is speaking (opening or follow-up), a candidate turn may begin
    # with the user pressing PTT. If the flow hasn't opened yet, open first.
    if not flow.opened:
        opening = flow.opening_line()
        mp3 = synthesize(opening)
        return {"text": "", "spoken": opening, "next_question": opening, "done": flow.done,
                "audio_b64": base64.b64encode(mp3).decode(), "section": flow.section_for_ui(),
                "phase": flow.phase, "opening": True}
    if req.audio_b64:
        try:
            text = transcribe_flash(req.audio_b64, req.format)
        except Exception:
            text = ""
        if not text:
            # Nothing recognized: return the current question but do NOT advance.
            cur = next((t["content"] for t in reversed(flow.turns) if t.get("role") == "assistant"), "")
            mp3 = synthesize(cur or flow.opening_line())
            return {"text": "", "spoken": cur, "next_question": cur, "done": flow.done,
                    "audio_b64": base64.b64encode(mp3).decode(), "section": flow.section_for_ui(),
                    "phase": flow.phase}
        speak = flow.next_line(text)
    else:
        speak = flow.opening_line()
    mp3 = synthesize(speak)
    return {"text": text if req.audio_b64 else "", "spoken": speak, "next_question": speak,
            "done": flow.done, "audio_b64": base64.b64encode(mp3).decode(),
            "section": flow.section_for_ui(), "phase": flow.phase}


@app.websocket("/ws/voice")
async def ws_voice(websocket: WebSocket, interview_id: str = ""):
    """Full-duplex phone-call voice channel: streaming STT partials + streaming
    TTS chunks on one socket, interruptible (barge-in). See voice_ws.py."""
    await voice_ws_handler(websocket, interview_id)


# ---------------------------------------------------------------------------
# Hand-code coding round: agent sees & judges the candidate's code
# ---------------------------------------------------------------------------
class CodingJudgeRequest(BaseModel):
    interview_id: str
    code: str = ""
    language: str = "python"


def _coding_question(ctx: InterviewContext):
    return next((q for q in ctx.plan.questions if q.section == "coding"), None)


@app.get("/api/interviews/{interview_id}/problem")
def get_coding_problem(interview_id: str):
    ctx = _require_ctx(interview_id)
    q = _coding_question(ctx)
    if q is None:
        return {"problem": None, "question_text": None}
    prob = load_problem(q.problem_id)
    return {"problem_id": q.problem_id, "question_text": q.text, "problem": prob}


@app.post("/api/coding/judge")
def coding_judge(req: CodingJudgeRequest, user: dict = Depends(_auth_user)):
    _check_owner(req.interview_id, user)
    ctx = _require_ctx(req.interview_id)
    q = _coding_question(ctx)
    prob = load_problem(q.problem_id) if q else None
    verdict = judge_code(prob, req.code, req.language)
    return verdict


# ---------------------------------------------------------------------------
# Screen / image reading via Gemini vision (the "AI 看屏幕" capability)
# ---------------------------------------------------------------------------
class VisionCall(BaseModel):
    image_b64: str
    prompt: str = "请读取并简要描述这个画面里最重要的内容。"
    mime: str = "image/png"


@app.post("/api/vision/analyze")
def vision_analyze(req: VisionCall):
    try:
        llm = LLM()
        # Prefer Kimi Code K2.7 for screen reading (fast, stable); fall back to Gemini.
        if get_settings().kimi_api_key:
            return {"description": llm.vision_kimi(req.prompt, req.image_b64, req.mime)}
        return {"description": llm.vision(req.prompt, req.image_b64, req.mime)}
    except Exception as e:
        return {"description": "", "error": str(e)}


@app.post("/api/vision/analyze-batch")
async def vision_analyze_batch(req: dict):
    """并发读多帧屏幕图（video stream 的"一帧一帧看"）。返回每帧的描述。

    req: {frames: [{data, mime}...], prompt?}  并发上限 ~10。
    前端把返回的描述逐条 POST 到 /screen-note，agent 拿到连续画面旁注。
    """
    import asyncio
    import concurrent.futures as cf

    frames = req.get("frames") if isinstance(req.get("frames"), list) else []
    if not frames:
        raise HTTPException(400, "no frames")
    prompt = str(req.get("prompt", "这是屏幕录屏的一帧。用一句中文简述画面最重要内容，不超过30字。"))
    llm = LLM()
    use_kimi = bool(get_settings().kimi_api_key)

    def one(fr: dict) -> str:
        b64 = str(fr.get("data", ""))
        mime = str(fr.get("mime", "image/jpeg"))
        if not b64:
            return ""
        try:
            if use_kimi:
                return llm.vision_kimi(prompt, b64, mime, timeout=60)
            return llm.vision(prompt, b64, mime, timeout=60)
        except Exception as exc:  # noqa: BLE001
            return f"(reading failed: {exc})"

    # True concurrency: submit each frame's vision call to a thread pool and await
    # them all together (ThreadPoolExecutor.map is lazy -> would serialize; use submit).
    loop = asyncio.get_running_loop()
    with cf.ThreadPoolExecutor(max_workers=min(10, len(frames))) as ex:
        futs = [loop.run_in_executor(ex, lambda fr=fr: one(fr)) for fr in frames[:10]]
        results = await asyncio.gather(*futs)
    return {"frames": [{"index": i, "description": r} for i, r in enumerate(results)]}


# ---------------------------------------------------------------------------
# LiveKit agent presence + recording + "agent sees screen" (server half).
# The real agent participant is a browser shim (web AgentPresence) that joins
# with the JWT minted by agent-join; REST here ensures the room, tracks
# participants/screen-share tracks and controls egress recording.
# ---------------------------------------------------------------------------
def _require_livekit() -> None:
    if not livekit_configured():
        raise HTTPException(503, "LiveKit not configured (LIVEKIT_API_KEY/SECRET missing)")


@app.post("/api/interviews/{interview_id}/agent-join")
async def agent_join(interview_id: str, user: Optional[dict] = Depends(_optional_user)):
    """Call once the interview room is live: ensure room + mint agent token +
    best-effort start recording. Returns connection details for the browser shim."""
    _check_owner(interview_id, user)
    _require_livekit()
    try:
        return await livekit_agent_join(interview_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("agent-join failed for %s", interview_id)
        raise HTTPException(502, f"LiveKit agent join failed: {exc}")


@app.post("/api/interviews/{interview_id}/agent-leave")
async def agent_leave(interview_id: str, user: Optional[dict] = Depends(_optional_user)):
    """Stop recording and remove the agent participant (interview ended)."""
    _check_owner(interview_id, user)
    _require_livekit()
    try:
        return await livekit_agent_leave(interview_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"LiveKit agent leave failed: {exc}")


@app.get("/api/interviews/{interview_id}/agent/status")
async def agent_status(interview_id: str, user: Optional[dict] = Depends(_optional_user)):
    """Room participants + published tracks + whether the agent is present."""
    _check_owner(interview_id, user)
    _require_livekit()
    try:
        return await livekit_room_status(interview_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"LiveKit status failed: {exc}")


@app.get("/api/interviews/{interview_id}/agent/screenshare")
async def agent_screenshare(interview_id: str, user: Optional[dict] = Depends(_optional_user)):
    """Server-side view of published screen-share tracks in the interview room.

    The LiveKit REST API can list the screen-share track (source, dimensions,
    publisher) but has NO pixel access — frames are only available to a
    subscribed participant. The browser shim (AgentPresence) subscribes to this
    track, downsamples frames and POSTs them to /api/vision/analyze (Gemini).
    """
    _check_owner(interview_id, user)
    _require_livekit()
    try:
        st = await livekit_room_status(interview_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"LiveKit status failed: {exc}")
    return {
        "ok": st.get("ok"),
        "room": st.get("room"),
        "screenshare": st.get("screenshare", []),
        "note": "Track metadata only (REST has no frames); subscribe client-side "
                "and send frames to /api/vision/analyze for Gemini reading.",
    }


# ---------------------------------------------------------------------------
# Info search (小红书 / 知乎 / 牛客 / 搜索引擎) — multi-engine, best-effort.
# ---------------------------------------------------------------------------
class SearchRequest(BaseModel):
    query: str
    limit: int = 50


@app.post("/api/search")
def search(req: SearchRequest):
    from .researcher.providers import get_providers, run_queries

    query = (req.query or "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    limit = max(3, min(req.limit, 100))
    providers = [p for p in get_providers() if p.enabled]
    sources = run_queries(providers, [query], per_query=min(max(limit, 6), 40),
                          max_total=limit, deadline=limit * 1.1 + 20, workers=12)
    return {"query": query, "sources": [s.model_dump() for s in sources]}


class LLMPing(BaseModel):
    text: str = "你好，请用一句话介绍你自己。"
    system: str = ""


@app.post("/api/llm/ping")
def llm_ping(req: LLMPing):
    """LLM 接口连通性测试：发一段文本给 LLM，看是否返回（返回原文 + 模型的回答）。"""
    s = get_settings()
    if not s.llm_api_key:
        raise HTTPException(503, "LLM API key not configured")
    try:
        msgs = [{"role": "system", "content": req.system or "你是一个友好的 AI 助手。"},
                {"role": "user", "content": req.text}]
        out = LLM().chat(msgs, max_tokens=200, temperature=0.6, timeout=45.0)
        return {"ok": True, "model": s.llm_model, "prompt": req.text[:200], "reply": out}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Transcript + share + audio recap (Phase 5)
# ---------------------------------------------------------------------------
def _transcript_items(ctx: InterviewContext) -> list[dict]:
    plan_by_id = {q.id: q for q in ctx.plan.questions}
    items = []
    for a in ctx.answers:
        q = plan_by_id.get(a.question_id)
        if q and not a.transcript.startswith("[follow-up]"):
            items.append({"question": q.text, "answer": a.transcript, "section": q.section})
    return items


@app.get("/api/interviews/{interview_id}/transcript")
def get_transcript(interview_id: str):
    ctx = _require_ctx(interview_id)
    items = _transcript_items(ctx)
    text = "\n\n".join(f"Q({it['section']}): {it['question']}\nA: {it['answer']}" for it in items)
    return {"items": items, "text": text, "meta": {"position": ctx.job.position, "company": ctx.job.company}}


@app.get("/api/interviews/{interview_id}/recap")
def get_recap(interview_id: str):
    ctx = _require_ctx(interview_id)
    sc = ctx.scorecard if (ctx.scorecard and ctx.scorecard.items) else finalize(ctx)
    lines = [f"这是你的模拟面试报告，综合得分 {sc.overall} 分。"]
    for m in sc.interviewer_os.missing_slots[:3]:
        lines.append(f"你觉得可以改进的有：{m.slot}。{m.one_line_advice}。")
    lines.append("建议针对这些点重点练习，祝你求职顺利。")
    text = "".join(lines)
    mp3 = synthesize(text)
    return {"text": text, "audio_b64": base64.b64encode(mp3).decode(), "overall": sc.overall}


@app.get("/api/interviews/{interview_id}/summary")
def interview_summary(interview_id: str, user: Optional[dict] = Depends(_optional_user)):
    """汇总本次面试的全部信息，生成一份可下载/查看的 Markdown 修改建议文档。

    包含：岗位/候选人概览、各环节提问与回答、逐项评分、缺失项(为什么在意/想听到什么/
    一句话建议)、以及给候选人的改进建议与复习重点。
    """
    ctx = _require_ctx(interview_id)
    sc = ctx.scorecard if (ctx.scorecard and ctx.scorecard.items) else finalize(ctx)
    os_ = sc.interviewer_os
    items = _transcript_items(ctx)
    flow = _FLOWS.get(interview_id)
    strictness = getattr(flow, "strictness", "standard") if flow else "standard"
    persona = getattr(flow, "ctx", ctx).persona if flow else getattr(ctx, "persona", "high-peer")

    sec_order = ctx.plan.sections_order
    sec_label = {"intro": "自我介绍", "behavioral": "项目/经历", "technical": "技术/项目细节",
                 "coding": "手撕代码", "wrap": "收尾"}

    L: list[str] = []
    L.append(f"# 模拟面试总结报告 · {ctx.job.position} @ {ctx.job.company}\n")
    L.append(f"**候选人**：{ctx.candidate.name}  ·  **综合得分**：{sc.overall}/100\n")
    L.append(f"**岗位**：{ctx.job.position}（{ctx.job.seniority}）@{ctx.job.company}\n")
    L.append(f"**面试官人格**：{persona}  |  **严格程度**：{strictness}  |  **覆盖环节**：{'、'.join(sec_label.get(s, s) for s in sec_order)}\n")

    # 逐环节：提问 + 回答
    L.append("\n## 一、面试过程（逐环节）\n")
    by_sec: dict[str, list[dict]] = {}
    for it in items:
        by_sec.setdefault(it["section"], []).append(it)
    for s in sec_order:
        label = sec_label.get(s, s)
        block = by_sec.get(s, [])
        L.append(f"### {label}\n")
        if not block:
            L.append("（本环节未作答）\n")
        for it in block:
            L.append(f"**Q**：{it['question']}\n")
            L.append(f"**A**：{it['answer']}\n")

    # 逐项评分
    L.append("\n## 二、分项评分\n")
    for it in sc.items:
        L.append(f"- **{it.competency}**：{it.score}/5（{it.level}）— {it.evidence}\n")

    # 缺失项 / 面试官想听到什么
    L.append("\n## 三、面试官想重点听到的（missing slots）\n")
    for m in os_.missing_slots[:8]:
        L.append(f"### {m.slot}\n")
        L.append(f"- 为什么在意：{m.why_it_matters}\n")
        L.append(f"- 想听到：{'；'.join(m.what_i_want_to_hear)}\n")
        L.append(f"- 一句话建议：{m.one_line_advice}\n")
    if not os_.missing_slots:
        L.append("（无突出缺失项）\n")
    if os_.hidden_concern:
        L.append(f"\n**面试官隐忧**：{os_.hidden_concern}\n")

    # 改进建议汇总
    L.append("\n## 四、改进建议\n")
    for ns in sc.next_steps:
        L.append(f"- {ns}\n")
    L.append("\n---\n*本报告由 ProbeDesk 自动生成，综合本次面试全部问答与评分。*")
    text = "\n".join(L)
    return {"markdown": text, "overall": sc.overall}

