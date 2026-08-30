"""LiveKit room/agent orchestration for the interviewer (server side only).

REST integration via the official Python SDK (`livekit-api`, `from livekit
import api`). The LiveKit REST API can create/list rooms, list participants and
their published tracks, and control egress recording — but it CANNOT make a
participant join a room (participants always connect over WebSocket with a JWT).

So the "agent" participant is a browser shim (apps/web AgentPresence): the
frontend calls `agent-join` once the interview room is live, gets a JWT minted
here, and the browser opens a second (hidden) LiveKit connection under the
`agent-interviewer` identity that:
  - publishes an "AI 面试官" video tile   (agent is VIDEO-visible in the room)
  - publishes the TTS voice bus          (agent is AUDIBLE in the room + in
                                         the egress recording)
  - subscribes to the candidate's screen-share track, downsamples frames and
    sends them to /api/vision/analyze (Gemini)  (agent SEES the shared screen)

This module provides the server half: ensure room, mint token, room/participant
/screen-share status, and egress recording start/stop.

NOTE on recording: the self-hosted server (/data/livekit/config/livekit.yaml)
does NOT enable the egress service yet, so `start_room_composite_egress`
returns 503 ("no response from servers"). This module degrades gracefully and
reports `recording.status == "unavailable"` with the exact fix:
    livekit.yaml:  egress: { service: { enabled: true } }
    then restart livekit-server (docker restart livekit-server livekit-egress).
The egress container already mounts ./recordings -> /data/livekit/recordings on
the host, so DirectFileOutput MP4s land there.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from livekit import api
from livekit.protocol import egress as E
from livekit.protocol import room as R
from livekit.protocol import models as M  # TrackInfo / ParticipantInfo / TrackSource

from .config import get_settings

logger = logging.getLogger("agent.livekit_bridge")

# Stable identity of the interviewer participant inside every interview room.
AGENT_IDENTITY = "agent-interviewer"
AGENT_NAME = "AI 面试官"

# Host path that the egress container mounts (see /data/livekit/docker-compose.yml).
RECORDINGS_DIR = "/data/livekit/recordings"

_ACTIVE_STATUSES = (E.EgressStatus.EGRESS_STARTING, E.EgressStatus.EGRESS_ACTIVE)


def livekit_configured() -> bool:
    s = get_settings()
    return bool(s.livekit_api_key and s.livekit_api_secret)


def rest_url() -> str:
    """Derive the REST base URL from the ws URL (ws:// -> http://, wss:// -> https://)."""
    s = get_settings()
    u = urlparse(s.livekit_url)
    scheme = "https" if u.scheme == "wss" else "http"
    return f"{scheme}://{u.netloc}"


def public_url() -> str:
    """Browser-reachable server URL (internal ws://127.0.0.1:7880 is not reachable from clients)."""
    s = get_settings()
    return s.livekit_public_url or s.livekit_url


def room_name(interview_id: str) -> str:
    """Room name for an interview. Must match apps/web/api/livekit/token/[id]/route.ts."""
    safe = "".join(c for c in (interview_id or "") if c.isalnum() or c in "-_") or "interview"
    return f"probedesk-{safe}"


def mint_agent_token(interview_id: str) -> str:
    """JWT for the interviewer participant (publish tile+voice, subscribe screen)."""
    s = get_settings()
    at = (
        api.AccessToken(s.livekit_api_key, s.livekit_api_secret)
        .with_identity(AGENT_IDENTITY)
        .with_name(AGENT_NAME)
        .with_ttl(timedelta(minutes=60))
        .with_grants(
            api.VideoGrants(
                room=room_name(interview_id),
                room_join=True,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
    )
    return at.to_jwt()


def _api() -> api.LiveKitAPI:
    s = get_settings()
    return api.LiveKitAPI(rest_url(), s.livekit_api_key, s.livekit_api_secret)


def _track_summary(t: M.TrackInfo) -> dict:
    return {
        "sid": t.sid,
        "source": t.source,  # models.TrackSource (3 == SCREEN_SHARE)
        "type": t.type,
        "name": t.name,
        "muted": t.muted,
        "width": t.width or None,
        "height": t.height or None,
    }


def _participant_summary(p: M.ParticipantInfo) -> dict:
    return {
        "identity": p.identity,
        "name": p.name,
        "kind": p.kind,
        "tracks": [_track_summary(t) for t in p.tracks],
    }


# ---------------------------------------------------------------------------
# Room
# ---------------------------------------------------------------------------
async def ensure_room(interview_id: str) -> dict:
    rn = room_name(interview_id)
    try:
        async with _api() as lk:
            rooms = await lk.room.list_rooms(R.ListRoomsRequest(names=[rn]))
            if not any(r.name == rn for r in rooms.rooms):
                await lk.room.create_room(R.CreateRoomRequest(name=rn, empty_timeout=600))
                created = True
            else:
                created = False
        return {"ok": True, "room": rn, "created": created}
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_room(%s) failed: %s", rn, exc)
        return {"ok": False, "room": rn, "error": str(exc)}


async def room_status(interview_id: str) -> dict:
    """Participants + their tracks + screen-share tracks (server-side visibility)."""
    rn = room_name(interview_id)
    try:
        async with _api() as lk:
            parts = await lk.room.list_participants(R.ListParticipantsRequest(room=rn))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "room": rn, "exists": False, "error": str(exc),
                "participants": [], "screenshare": []}
    participants = [_participant_summary(p) for p in parts.participants]
    screenshare = [
        {"identity": p["identity"], **t}
        for p in participants
        for t in p["tracks"]
        if t["source"] == M.TrackSource.SCREEN_SHARE
    ]
    return {
        "ok": True,
        "room": rn,
        "exists": True,
        "agent_present": any(p["identity"] == AGENT_IDENTITY for p in participants),
        "participants": participants,
        "screenshare": screenshare,
    }


# ---------------------------------------------------------------------------
# Egress recording (best-effort; see module docstring re: 503)
# ---------------------------------------------------------------------------
async def start_recording(interview_id: str) -> dict:
    rn = room_name(interview_id)
    try:
        async with _api() as lk:
            existing = await lk.egress.list_egress(E.ListEgressRequest(room_name=rn))
            active = [e for e in existing.items if e.status in _ACTIVE_STATUSES]
            if active:
                return {"status": "active", "egress_id": active[0].egress_id, "room": rn}
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            req = E.RoomCompositeEgressRequest(
                room_name=rn,
                layout="speaker",
                file=E.EncodedFileOutput(
                    file_type=E.EncodedFileType.MP4,
                    filepath=f"{RECORDINGS_DIR}/{rn}-{ts}.mp4",
                ),
            )
            info = await lk.egress.start_room_composite_egress(req)
            return {"status": "started", "egress_id": info.egress_id, "room": rn}
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", None)
        status = getattr(exc, "status", None)
        reason = str(exc)
        egress_disabled = (
            "no response from servers" in reason
            or code == "unavailable"
            or str(status) in ("503", "unavailable")
        )
        hint = (
            "egress service not enabled on the livekit server — add "
            "`egress: { service: { enabled: true } }` to /data/livekit/config/livekit.yaml "
            "and restart livekit-server"
            if egress_disabled
            else None
        )
        logger.warning("start_recording(%s) failed: %s", rn, reason)
        return {"status": "unavailable", "error": reason, "hint": hint, "room": rn}


async def stop_recording(interview_id: str) -> dict:
    rn = room_name(interview_id)
    try:
        async with _api() as lk:
            existing = await lk.egress.list_egress(E.ListEgressRequest(room_name=rn))
            active = [e for e in existing.items if e.status in _ACTIVE_STATUSES]
            stopped = []
            for e in active:
                try:
                    await lk.egress.stop_egress(E.StopEgressRequest(egress_id=e.egress_id))
                    stopped.append(e.egress_id)
                except Exception as exc:  # noqa: BLE001
                    stopped.append(f"{e.egress_id}:{exc}")
            return {"status": "stopped" if stopped else "none", "stopped": stopped, "room": rn}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc), "room": rn}


# ---------------------------------------------------------------------------
# Agent presence
# ---------------------------------------------------------------------------
async def agent_join(interview_id: str) -> dict:
    """Idempotent: ensure the room, mint the agent token, best-effort recording."""
    room = await ensure_room(interview_id)
    token = mint_agent_token(interview_id)
    recording = await start_recording(interview_id)
    status = await room_status(interview_id)
    return {
        "ok": room.get("ok", False),
        "room": room_name(interview_id),
        "url": public_url(),
        "token": token,
        "agent_identity": AGENT_IDENTITY,
        "recording": recording,
        "agent_present": status.get("agent_present", False),
        "participants": status.get("participants", []),
        "error": room.get("error"),
    }


async def agent_leave(interview_id: str) -> dict:
    """Stop recording + remove the agent participant if present."""
    rn = room_name(interview_id)
    recording = await stop_recording(interview_id)
    removed = False
    try:
        async with _api() as lk:
            parts = await lk.room.list_participants(R.ListParticipantsRequest(room=rn))
            if any(p.identity == AGENT_IDENTITY for p in parts.participants):
                await lk.room.remove_participant(
                    R.RoomParticipantIdentity(room=rn, identity=AGENT_IDENTITY)
                )
                removed = True
        return {"ok": True, "room": rn, "agent_removed": removed, "recording": recording}
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_leave(%s) failed: %s", rn, exc)
        return {"ok": False, "room": rn, "agent_removed": removed,
                "recording": recording, "error": str(exc)}
