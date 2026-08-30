"""Offline tests for livekit_bridge pure helpers (no LiveKit server needed).

Run: cd apps/agent && .venv/bin/python -m pytest tests/test_livekit_bridge.py -q
"""

from agent.livekit_bridge import (
    AGENT_IDENTITY,
    public_url,
    rest_url,
    room_name,
)


def test_room_name_matches_web_token_route():
    # must be stable & sanitized (apps/web/api/livekit/token/[id]/route.ts uses probedesk-<id>)
    assert room_name("abc-123") == "probedesk-abc-123"
    assert room_name("../etc") == "probedesk-etc"
    assert room_name("") == "probedesk-interview"


def test_rest_url_derivation():
    # ws:// -> http:// so the REST client can talk to the same server
    assert rest_url() == "http://127.0.0.1:7880"


def test_public_url_defaults_to_wss():
    # browsers cannot reach the internal ws://127.0.0.1:7880
    assert public_url().startswith("wss://")


def test_agent_identity_stable():
    assert AGENT_IDENTITY == "agent-interviewer"
