"""Tests for the booking schedule / prep-light gate (asap + 30-min rule)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "src")

from fastapi.testclient import TestClient

from agent.main import app, _BOOKING_CFG, _CONTEXTS, _FAILED, _PENDING
from agent.contracts import (
    CandidateProfile, CompanyIntel, GapAnalysis, InterviewContext,
    InterviewerOS, JobSpec, PlannedQuestion, QuestionPlan, Scorecard, CodingTendency,
)

BAD = "00000000-0000-0000-0000-000000000000"
c = TestClient(app)


def _auth() -> dict[str, str]:
    r = c.post("/api/auth/register", json={"username": f"gate{datetime.utcnow().timestamp()}", "password": "secret123"})
    if r.status_code != 201:
        r = c.post("/api/auth/login", json={"username": "gate", "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_non_asap_future_rejected_when_less_than_30min():
    h = _auth()
    soon = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    r = c.post("/api/interviews/book", headers=h, json={"name": "x", "company": "c", "position": "p",
                                                       "jd_text": "j", "resume_text": "r", "scheduled_at": soon,
                                                       "has_coding": True, "scenario": "algorithm",
                                                       "persona": "high-peer", "mode": "text", "asap": False})
    assert r.status_code == 400, r.text


def test_non_asap_30min_ahead_accepted():
    h = _auth()
    t = (datetime.utcnow() + timedelta(minutes=40)).isoformat()
    r = c.post("/api/interviews/book", headers=h, json={"name": "x", "company": "c", "position": "p",
                                                       "jd_text": "j", "resume_text": "r", "scheduled_at": t,
                                                       "has_coding": True, "scenario": "algorithm",
                                                       "persona": "high-peer", "mode": "text", "asap": False})
    assert r.status_code == 201, r.text
    assert r.json()["asap"] is False


def test_asap_accepts_now():
    h = _auth()
    r = c.post("/api/interviews/book", headers=h, json={"name": "x", "company": "c", "position": "p",
                                                       "jd_text": "j", "resume_text": "r",
                                                       "has_coding": True, "scenario": "algorithm",
                                                       "persona": "high-peer", "mode": "text", "asap": True})
    assert r.status_code == 201, r.text
    assert r.json()["asap"] is True


def test_gated_answer_refuses_before_scheduled_and_proceeds_after():
    """A scheduled (non-asap) interview must refuse /answer before its time and
    accept it once the scheduled time has passed (or when asap)."""
    h = _auth()
    future = (datetime.utcnow() + timedelta(minutes=45)).isoformat()
    b = c.post("/api/interviews/book", headers=h, json={"company": "c", "position": "p", "jd_text": "j",
                                                       "resume_text": "r", "scheduled_at": future,
                                                       "has_coding": True, "scenario": "algorithm",
                                                       "persona": "high-peer", "mode": "text", "asap": False})
    bid = b.json()["id"]
    # start
    s = c.post(f"/api/interviews/{bid}/start", headers=h).json()
    iid = s["interview_id"]
    # Seed a context so _require_ctx passes (skip build_plan in the test).
    _seed_ctx(iid)
    # before time: answer should be gated
    r = c.post(f"/api/interviews/{iid}/answer", headers=h, json={"answer": "hi"})
    assert r.json().get("gated") is True, r.text
    # Force the gate open (treat as asap) -> proceeds
    _BOOKING_CFG[iid]["asap"] = True
    r2 = c.post(f"/api/interviews/{iid}/answer", headers=h, json={"answer": "hi"})
    assert r2.json().get("gated") is not True, r2.text
    assert r2.json().get("next_question") is not None


def _seed_ctx(iid: str) -> None:
    plan = QuestionPlan(sections_order=["intro", "technical", "coding", "wrap"],
                        questions=[PlannedQuestion(id="q0", section="coding", text="代码", difficulty=3,
                                                   rubric=[], followups=[], target_competency="hand-code", problem_id="two-sum")])
    ctx = InterviewContext(
        candidate=CandidateProfile(name="王", headline="后端", summary="后端", skills=["python"],
                                   experience=[], projects=[], level="mid", resume_hash="h"),
        job=JobSpec(position="后端", seniority="mid", company="c", must_have=[], nice_to_have=[],
                    tech_stack=[], responsibilities=[], jd_text="j"),
        company=CompanyIntel(summary="s", tech_stack=[], values=[], interview_process="", recent_news=[],
                             culture_notes="", coding_tendency=CodingTendency(prefers_live_coding=True, high_freq_topics=[], platform="leetcode"),
                             missing_company_info=True, sources=[]),
        gap=GapAnalysis(strengths=[], gaps=[], probe_targets=[], missing_skills=[]),
        plan=plan, cursor=0, answers=[],
        scorecard=Scorecard(overall=0, items=[], summary="", next_steps=[], model_answers=[],
                            interviewer_os=InterviewerOS(hidden_concern="", why_this_question=[], missing_slots=[], risk_level="low")),
        status="prep", persona="high-peer",
    )
    _CONTEXTS[iid] = ctx
    _PENDING.discard(iid)
    _FAILED.discard(iid)
