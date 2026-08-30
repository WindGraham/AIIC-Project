"""Offline API robustness: unknown ids must return 404 (never 500).

Run: cd apps/agent && .venv/bin/python -m pytest tests/test_api_robust.py -q
These paths don't touch the LLM/voice/search, so they're deterministic + fast."""

from fastapi.testclient import TestClient

from agent.main import app

BAD = "00000000-0000-0000-0000-000000000000"
c = TestClient(app)


def test_prepare_requires_fields_422():
    r = c.post("/api/interviews/prepare", json={"resume_text": "x"})  # missing company/position
    assert r.status_code == 422


def test_unknown_id_endpoints_404():
    assert c.get(f"/api/interviews/{BAD}/transcript").status_code == 404
    assert c.get(f"/api/interviews/{BAD}/recap").status_code == 404
    assert c.get(f"/api/interviews/{BAD}/next").status_code == 404
    assert c.post(f"/api/interviews/{BAD}/answer", json={"answer": "x"}).status_code == 404
    assert c.post("/api/coding/judge", json={"interview_id": BAD, "code": "x"}).status_code == 404
    assert c.post("/api/voice/answer", json={"interview_id": BAD, "audio_b64": ""}).status_code == 404
