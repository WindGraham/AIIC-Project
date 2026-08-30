"""Tests for the per-round live interviewer flow (liveflow.LiveFlow).

Verifies the DIRECTOR determinism (the phase ladder and time/turn budgets) WITHOUT
needing a real LLM: we monkeypatch LiveFlow._ask_agent to return canned lines, so
we can assert the phase transitions and that each round records an answer + a
PlannedQuestion for scoring. A separate test exercises the real prompt-building
(identity/resume/requirements/full-history) as string content rather than a live
network call.
"""

from __future__ import annotations

import datetime

from agent.contracts import (
    CandidateProfile,
    CompanyIntel,
    GapAnalysis,
    InterviewContext,
    InterviewerOS,
    JobSpec,
    PlannedQuestion,
    QuestionPlan,
    Scorecard,
    CodingTendency,
)
from agent.liveflow import LiveFlow


def _make_ctx(has_coding: bool = True) -> InterviewContext:
    plan = QuestionPlan(
        sections_order=["intro", "project", "technical", "coding", "wrap"] if has_coding else ["intro", "project", "technical", "wrap"],
        questions=[
            PlannedQuestion(id="q0", section="intro", text="请自我介绍", difficulty=1,
                            rubric=[], followups=[], target_competency="intro"),
            PlannedQuestion(id="q1", section="coding", text="写代码", difficulty=3,
                            rubric=[], followups=[], target_competency="hand-code", problem_id="two-sum"),
        ],
    )
    return InterviewContext(
        candidate=CandidateProfile(name="张三", headline="后端开发", summary="三年后端经验",
                                   skills=["python", "mysql"], experience=[], projects=[],
                                   level="mid", resume_hash="abc"),
        job=JobSpec(position="后端开发工程师", seniority="mid", company="字节",
                    must_have=["python"], nice_to_have=["k8s"], tech_stack=["python", "mysql"],
                    responsibilities=[], jd_text="jd"),
        company=CompanyIntel(summary="", tech_stack=["python"], values=[], interview_process="",
                             recent_news=[], culture_notes="",
                             coding_tendency=CodingTendency(prefers_live_coding=True, high_freq_topics=[], platform="leetcode"),
                             missing_company_info=True, sources=[]),
        gap=GapAnalysis(strengths=["python"], gaps=["算法"], probe_targets=["项目A"], missing_skills=[]),
        plan=plan,
        cursor=0, answers=[], scorecard=Scorecard(overall=0, items=[], summary="", next_steps=[],
                                                 model_answers=[], interviewer_os=InterviewerOS(
                                                     hidden_concern="", why_this_question=[], missing_slots=[], risk_level="low")),
        status="prep", persona="high-peer",
    )


def test_opening_line_requests_self_intro():
    ctx = _make_ctx()
    flow = LiveFlow(ctx)
    line = flow.opening_line()
    assert "自我介绍" in line
    assert len(flow.turns) == 1
    assert flow.turns[0]["role"] == "assistant"
    assert flow.phase == "intro"


def test_phase_ladder_reaches_coding_then_wrap(monkeypatch):
    """The director should move intro -> project -> probe -> coding -> wrap, and
    the per-round agent output is whatever the (mocked) LLM says."""
    ctx = _make_ctx(has_coding=True)
    flow = LiveFlow(ctx, probe_max_turns=2, coding_max_turns=1)
    calls = {"n": 0}

    def fake_ask(_self):
        calls["n"] += 1
        return {
            "intro": "请先自我介绍。",
            "project": "请介绍项目A。",
            "probe": "这个项目有什么难点？",
            "coding": "请开始写代码。",
            "wrap": "感谢，再见。",
        }[flow.phase]

    monkeypatch.setattr(LiveFlow, "_ask_agent", fake_ask)
    flow.opening_line()

    # Turn 1 (answer intro) -> project
    line1 = flow.next_line("我叫张三，毕业于XX大学。")
    assert flow.phase == "project"

    # Turn 2 (answer project) -> probe
    line2 = flow.next_line("我做过项目A，负责后端。")
    assert flow.phase == "probe"

    # probe_max_turns=2 so after 2 probe answers -> coding
    flow.next_line("项目难点是性能优化。")
    assert flow.phase == "probe"
    flow.next_line("我用了缓存。")
    assert flow.phase == "coding"
    assert flow.coding_announced

    # coding_max_turns=1 so one coding answer -> wrap (not done until wrap spoken)
    flow.next_line("代码思路是这样。")
    assert flow.phase == "wrap"
    assert not flow.done, "done must not fire until the wrap line is spoken"

    # wrap gets spoken; after it, done fires
    wrap_line = flow.next_line("谢谢面试官。")
    assert flow.done
    assert wrap_line == "感谢，再见。"


def test_no_coding_skips_to_wrap(monkeypatch):
    ctx = _make_ctx(has_coding=False)
    flow = LiveFlow(ctx)

    def fake_ask(_self):
        return "好的，请继续。"

    monkeypatch.setattr(LiveFlow, "_ask_agent", fake_ask)
    flow.opening_line()
    # After intro+project answers, we should reach probe (not coding).
    flow.next_line("我叫张三。")
    flow.next_line("我做过项目A。")
    # Even after many turns we never hit coding.
    for _ in range(3):
        flow.next_line("细节。")
    assert "coding" not in [flow.phase]


def test_each_round_records_answer_and_question_for_scoring(monkeypatch):
    ctx = _make_ctx()
    flow = LiveFlow(ctx)

    def fake_ask(_self):
        return "这是问题。"

    monkeypatch.setattr(LiveFlow, "_ask_agent", fake_ask)
    flow.opening_line()
    before_q = len(ctx.plan.questions)
    before_a = len(ctx.answers)
    flow.next_line("这是回答。")
    # The flow appends a new PlannedQuestion + an AnswerRecord for scoring.
    assert len(ctx.plan.questions) == before_q + 1
    assert len(ctx.answers) == before_a + 1
    assert ctx.answers[-1].transcript == "这是回答。"


def test_prompt_contains_identity_resume_requirements_and_history(monkeypatch):
    """The per-round agent prompt must include persona identity, candidate resume,
    this interview's requirements, and the full chat history."""
    ctx = _make_ctx()
    flow = LiveFlow(ctx, notes="重点考察算法", scenario="algorithm")
    captured: dict = {}

    def fake_chat(self, messages, **kwargs):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        return "继续。"

    flow.next_line = flow.next_line  # no-op
    # Call the real _ask_agent but stub the LLM.chat used inside it.
    import agent.liveflow as lf
    monkeypatch.setattr(lf, "LLM", lambda: type("L", (), {"chat": fake_chat, "chat_json": lambda *a, **k: {}})())

    flow.turns = [{"role": "assistant", "content": "请自我介绍。"}, {"role": "user", "content": "我叫张三。"}]
    line = flow._ask_agent()
    assert line == "继续。"
    sys = captured["system"]
    # identity / persona
    assert "资深" in sys or "面试官" in sys
    # resume
    assert "张三" in sys and "后端开发" in sys
    # requirements
    assert "字节" in sys and "重点考察算法" in sys
    # full history
    assert "我叫张三" in captured["user"] and "请自我介绍" in (captured["user"] or "")
