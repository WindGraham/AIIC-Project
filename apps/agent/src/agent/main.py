"""Phase-0 minimal FastAPI app: health + booking/interview CRUD over an
in-memory repo (the "agent API is the single source of truth" light path).
Live interviewer logic (prep/live/post + voice) is layered on in later phases."""

import base64
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings
from .store import PERSONA_LEVELS, get_store
from .contracts import InterviewContext
from .coding import judge_code, load_problem
from .llm import LLM
from .pipeline import ask_current, current_question, finalize, record_answer
from .prep import build_plan
from .stt import transcribe_flash
from .tts import synthesize

app = FastAPI(title="aiic-agent", version="0.1.0")

# in-memory contexts keyed by interview id (transient per live run)
_CONTEXTS: dict[str, InterviewContext] = {}
_MAX_CONTEXTS = 500  # guard against unbounded memory growth from unauthed prep


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
    if not payload.name:
        payload.name = f"{payload.position or '模拟'}面试"
    get_store().save_booking(user["id"], payload.model_dump())
    return payload


@app.get("/api/interviews")
def list_interviews(user: dict = Depends(_auth_user)):
    out = []
    for b in get_store().list_bookings(user["id"]):
        scheduled = b.get("scheduled_at")
        try:
            delta = (datetime.fromisoformat(str(scheduled)) - datetime.utcnow()).total_seconds()
        except Exception:
            delta = 0
        out.append({
            **b,
            "seconds_until_start": int(max(0, delta)),
            "status": "available" if delta <= 0 else "scheduled",
        })
    out.sort(key=lambda x: x.get("scheduled_at", ""))
    return out


@app.post("/api/interviews/{booking_id}/start", status_code=201)
def start_interview(booking_id: str, user: dict = Depends(_auth_user)):
    b = get_store().get_booking(user["id"], booking_id)
    if b is None:
        raise HTTPException(404, "booking not found")
    # reuse the booking fields to build the interview context (real LLM prep)
    persona = b.get("persona", "high-peer") if b.get("persona") in PERSONA_LEVELS else "high-peer"
    ctx = build_plan(b.get("resume_text", ""), b.get("jd_text", ""), b.get("company", ""),
                     b.get("position", ""), "mid", "zh", persona=persona)
    iid = str(uuid.uuid4())
    _put_context(iid, ctx)
    from .pipeline import ask_current as _ask
    return {
        "interview_id": iid,
        "booking_id": booking_id,
        "question": _ask(ctx),
        "plan": {"sections_order": ctx.plan.sections_order,
                 "questions": [{"id": q.id, "section": q.section, "text": q.text,
                                "difficulty": q.difficulty, "problem_id": q.problem_id} for q in ctx.plan.questions]},
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


@app.get("/api/interviews/{interview_id}/next")
def next_question(interview_id: str):
    ctx = _CONTEXTS.get(interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
    q = ask_current(ctx)
    cq = current_question(ctx)
    return {"question": q, "done": q is None, "section": cq.section if cq else None}


@app.post("/api/interviews/{interview_id}/answer")
def answer(interview_id: str, req: dict):
    ctx = _CONTEXTS.get(interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
    nxt = record_answer(ctx, str(req.get("answer", "")))
    cq = current_question(ctx)
    return {"next_question": nxt, "done": nxt is None, "section": cq.section if cq else None}


@app.get("/api/interviews/{interview_id}/report")
def report(interview_id: str):
    ctx = _CONTEXTS.get(interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
    sc = finalize(ctx)
    os_ = sc.interviewer_os
    return {
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
def voice_answer(req: VoiceAnswer):
    ctx = _CONTEXTS.get(req.interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
    q = ask_current(ctx)
    if q is None:
        sc = finalize(ctx)
        mp3 = synthesize("面试结束，感谢你的回答，可以查看你的报告了。")
        return {"done": True, "text": "", "spoken": "面试结束，感谢你的回答。", "next_question": None,
                "audio_b64": base64.b64encode(mp3).decode(), "report": True}
    if req.audio_b64:
        try:
            text = transcribe_flash(req.audio_b64, req.format)
        except Exception:
            text = ""
        nxt = record_answer(ctx, text)
    else:
        text, nxt = "", q  # start turn: speak the current question
    speak = nxt if nxt else "面试结束，感谢你的回答，可以查看你的报告了。"
    mp3 = synthesize(speak)
    cq = current_question(ctx)
    return {"text": text, "spoken": speak, "next_question": nxt, "done": nxt is None,
            "audio_b64": base64.b64encode(mp3).decode(), "section": cq.section if cq else None}


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
    ctx = _CONTEXTS.get(interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
    q = _coding_question(ctx)
    if q is None:
        return {"problem": None, "question_text": None}
    prob = load_problem(q.problem_id)
    return {"problem_id": q.problem_id, "question_text": q.text, "problem": prob}


@app.post("/api/coding/judge")
def coding_judge(req: CodingJudgeRequest):
    ctx = _CONTEXTS.get(req.interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
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
    ctx = _CONTEXTS.get(interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
    items = _transcript_items(ctx)
    text = "\n\n".join(f"Q({it['section']}): {it['question']}\nA: {it['answer']}" for it in items)
    return {"items": items, "text": text, "meta": {"position": ctx.job.position, "company": ctx.job.company}}


@app.get("/api/interviews/{interview_id}/recap")
def get_recap(interview_id: str):
    ctx = _CONTEXTS.get(interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
    sc = ctx.scorecard if (ctx.scorecard and ctx.scorecard.items) else finalize(ctx)
    lines = [f"这是你的模拟面试报告，综合得分 {sc.overall} 分。"]
    for m in sc.interviewer_os.missing_slots[:3]:
        lines.append(f"你觉得可以改进的有：{m.slot}。{m.one_line_advice}。")
    lines.append("建议针对这些点重点练习，祝你求职顺利。")
    text = "".join(lines)
    mp3 = synthesize(text)
    return {"text": text, "audio_b64": base64.b64encode(mp3).decode(), "overall": sc.overall}
