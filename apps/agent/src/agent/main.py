"""Phase-0 minimal FastAPI app: health + booking/interview CRUD over an
in-memory repo (the "agent API is the single source of truth" light path).
Live interviewer logic (prep/live/post + voice) is layered on in later phases."""

import base64
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings
from .contracts import InterviewContext
from .pipeline import ask_current, finalize, record_answer
from .prep import build_plan
from .stt import transcribe_flash
from .tts import synthesize

app = FastAPI(title="aiic-agent", version="0.1.0")

# in-memory contexts keyed by interview id (swap for Supabase later without changing callers)
_CONTEXTS: dict[str, InterviewContext] = {}


# ---------------------------------------------------------------------------
# Domain models (booking -> interview). Full InterviewContext lives in
# contracts.InterviewContext and is produced by the prep phase.
# ---------------------------------------------------------------------------
class Booking(BaseModel):
    id: str
    resume_id: str
    company: str
    position: str
    jd_text: str
    scheduled_at: datetime
    notes: str = ""
    has_coding: bool = True
    scenario: str = "algorithm"  # algorithm | retest
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
# In-memory store (light path; swap for Supabase without changing callers).
# ---------------------------------------------------------------------------
_STORE: dict[str, dict] = {"bookings": {}, "interviews": {}}


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


@app.post("/api/bookings", response_model=Booking, status_code=201)
def create_booking(payload: Booking):
    payload.id = payload.id or str(uuid.uuid4())
    _STORE["bookings"][payload.id] = payload.model_dump()
    return payload


@app.get("/api/bookings/{booking_id}", response_model=Booking)
def get_booking(booking_id: str):
    if booking_id not in _STORE["bookings"]:
        raise HTTPException(404, "booking not found")
    return _STORE["bookings"][booking_id]


@app.get("/api/interviews", response_model=list[Interview])
def list_interviews():
    return list(_STORE["interviews"].values())


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
    _CONTEXTS[interview_id] = ctx
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
    return {"question": q, "done": q is None}


@app.post("/api/interviews/{interview_id}/answer")
def answer(interview_id: str, req: dict):
    ctx = _CONTEXTS.get(interview_id)
    if ctx is None:
        raise HTTPException(404, "interview not prepared")
    nxt = record_answer(ctx, str(req.get("answer", "")))
    return {"next_question": nxt, "done": nxt is None}


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
    return {"text": text, "spoken": speak, "next_question": nxt, "done": nxt is None,
            "audio_b64": base64.b64encode(mp3).decode()}
