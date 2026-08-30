"""Offline API robustness: unknown ids must return 404 (never 500).

Run: cd apps/agent && .venv/bin/python -m pytest tests/test_api_robust.py -q
These paths don't touch the LLM/voice/search, so they're deterministic + fast.
"""

from fastapi.testclient import TestClient

from agent.main import app

BAD = "00000000-0000-0000-0000-000000000000"
c = TestClient(app)

# Routes that require auth return 401 unauthenticated and 404 for an unknown id
# once authenticated. We authenticate a throwaway user for those.
_auth_headers: dict[str, str] = {}


def _auth() -> dict[str, str]:
    if _auth_headers:
        return _auth_headers
    # Register a throwaway user; if it already exists, log in instead.
    r = c.post("/api/auth/register", json={"username": "robustness", "password": "secret123"})
    if r.status_code != 201:
        r = c.post("/api/auth/login", json={"username": "robustness", "password": "secret123"})
    token = r.json()["token"]
    _auth_headers["Authorization"] = f"Bearer {token}"
    return _auth_headers


def test_prepare_requires_fields_422():
    r = c.post("/api/interviews/prepare", json={"resume_text": "x"})  # missing company/position
    assert r.status_code == 422


def test_opt_auth_routes_unknown_id_404():
    # These take _optional_user and must 404 for an unknown id (even unauthenticated).
    assert c.get(f"/api/interviews/{BAD}/transcript").status_code == 404
    assert c.get(f"/api/interviews/{BAD}/recap").status_code == 404
    assert c.get(f"/api/interviews/{BAD}/next").status_code == 404


def test_auth_routes_unauth_401():
    # These require _auth_user, so unauthenticated requests are 401, never 404/500.
    assert c.post(f"/api/interviews/{BAD}/answer", json={"answer": "x"}).status_code == 401
    assert c.post("/api/coding/judge", json={"interview_id": BAD, "code": "x"}).status_code == 401
    assert c.post("/api/voice/answer", json={"interview_id": BAD, "audio_b64": ""}).status_code == 401


def test_auth_routes_unknown_id_404_when_authenticated():
    h = _auth()
    assert c.post(f"/api/interviews/{BAD}/answer", json={"answer": "x"}, headers=h).status_code == 404
    assert c.post("/api/coding/judge", json={"interview_id": BAD, "code": "x"}, headers=h).status_code == 404
    assert c.post("/api/voice/answer", json={"interview_id": BAD, "audio_b64": ""}, headers=h).status_code == 404
