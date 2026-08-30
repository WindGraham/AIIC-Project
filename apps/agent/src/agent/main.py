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
# interview_id -> owner user_id, set at /start. Used to gate the live interview
# endpoints & /report persistence to the interviewer's owner (cross-user safety).
_OWNER: dict[str, str] = {}
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
    company: str = ""
    position: str = ""
    jd_text: str = ""
    scheduled_at: datetime = Field(default_factory=datetime.utcnow)
    notes: str = ""
    has_coding: bool = True
    scenario: str = "algorithm"  # algorithm | retest(保研复试占位)
    persona: str = "high-peer"   # peer | high-peer | manager
    mode: str = "duplex"         # text | ptt | duplex (面试方案)
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
    """Opportunistic hygiene on boot: drop expired sessions."""
    try:
        get_store().purge_expired_sessions()
    except Exception:
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
    # Validate persona against the allow-list (block prompt-injection into the
    # interviewer-planning LLM via the persona field).
    if payload.persona not in PERSONA_LEVELS:
        payload.persona = "high-peer"
    # Validate interview mode (text | ptt | duplex).
    if payload.mode not in MODES:
        payload.mode = "duplex"
    if not payload.name:
        payload.name = f"{payload.position or '模拟'}面试"
    get_store().save_booking(user["id"], payload.model_dump())
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
        out.append({
            **b,
            "seconds_until_start": int(max(0, delta)),
            "status": "available" if delta <= 0 else "scheduled",
        })
    out.sort(key=lambda x: x.get("scheduled_at", ""))
    return out


@app.post("/api/interviews/{booking_id}/start", status_code=202)
def start_interview(booking_id: str, user: dict = Depends(_auth_user)):
    b = get_store().get_booking(user["id"], booking_id)
    if b is None:
        raise HTTPException(404, "booking not found")
    iid = str(uuid.uuid4())
    persona = b.get("persona", "high-peer") if b.get("persona") in PERSONA_LEVELS else "high-peer"
    _PENDING.add(iid)
    _OWNER[iid] = user["id"]
    _BOOKING_CFG[iid] = {
        "has_coding": bool(b.get("has_coding", True)),
        "notes": b.get("notes", ""),
        "scenario": b.get("scenario", "algorithm"),
        "persona": persona,
    }

    def _do_start():
        """Run build_plan (search + LLM) in a worker; store the context when done."""
        try:
            persona_inner = b.get("persona", "high-peer") if b.get("persona") in PERSONA_LEVELS else "high-peer"
            ctx = build_plan(b.get("resume_text", ""), b.get("jd_text", ""), b.get("company", ""),
                             b.get("position", ""), "mid", "zh", persona=persona_inner,
                             memory_brief=_history_brief(user["id"], b.get("position", "")))
            _put_context(iid, ctx)
        except Exception as exc:  # noqa: BLE001
            logger.exception("prep failed for %s: %s", booking_id, exc)
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
    token = get_store().create_session(user["id"])
    return {"user": user, "token": token}


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


def _ctx(interview_id: str) -> tuple[Optional[InterviewContext], bool]:
    """(context, is_preparing). We treat iid missing from _PENDING as a hard 404."""
    ctx = _CONTEXTS.get(interview_id)
    if ctx is not None:
        return ctx, False
    # not built yet: if it's a known pending prep, report preparing (not 404)
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
    ctx, preparing = _ctx(interview_id)
    if preparing:
        return {"status": "preparing", "question": None, "done": False, "section": None}
    # Every live interview is driven by the per-round LiveFlow agent.
    flow = _flow_for(interview_id)
    opening = flow.opening_line()  # idempotent
    return {
        "question": opening,
        "done": flow.done,
        "section": flow.section_for_ui(),
        "phase": flow.phase,
        "liveflow": True,
    }


@app.post("/api/interviews/{interview_id}/answer")
def answer(interview_id: str, req: dict, user: dict = Depends(_auth_user)):
    _check_owner(interview_id, user)
    _require_ctx(interview_id)
    txt = str(req.get("answer", "")).strip()
    flow = _flow_for(interview_id)
    if not txt:
        # No text yet: (re)seed the opening question.
        opening = flow.opening_line()
        return {"next_question": opening, "done": flow.done, "section": flow.section_for_ui(),
                "phase": flow.phase}
    if not flow.opened:
        # The candidate answered before the agent spoke (defensive): open first,
        # then treat the text as this first answer.
        flow.opening_line()
    nxt = flow.next_line(txt)
    return {"next_question": nxt, "done": flow.done, "section": flow.section_for_ui(),
            "phase": flow.phase}


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
    ctx = _require_ctx(req.interview_id)
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
    return {"text": req.audio_b64 and "…" or "", "spoken": speak, "next_question": speak,
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
        return {"description": LLM().vision(req.prompt, req.image_b64, req.mime)}
    except Exception as e:
        return {"description": "", "error": str(e)}


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
    limit: int = 10


@app.post("/api/search")
def search(req: SearchRequest):
    from .researcher.providers import get_providers, run_queries

    query = (req.query or "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    providers = [p for p in get_providers() if p.enabled]
    sources = run_queries(providers, [query], per_query=min(max(req.limit, 3), 10),
                          max_total=req.limit, deadline=45.0, workers=6)
    return {"query": query, "sources": [s.model_dump() for s in sources]}


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
