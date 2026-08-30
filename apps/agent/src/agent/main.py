"""Phase-0 minimal FastAPI app: health + booking/interview CRUD over an
in-memory repo (the "agent API is the single source of truth" light path).
Live interviewer logic (prep/live/post + voice) is layered on in later phases."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import get_settings

app = FastAPI(title="aiic-agent", version="0.1.0")


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
        "stt": {"deepgram": bool(s.deepgram_api_key), "model": s.stt_model},
        "tts": {"elevenlabs": bool(s.elevenlabs_api_key), "model": s.tts_model},
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
