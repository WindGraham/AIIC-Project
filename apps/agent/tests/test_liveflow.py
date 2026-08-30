"""Tests for the interview STATE MACHINE (liveflow.LiveFlow).

Verifies the state-machine determinism WITHOUT needing a real LLM: we monkeypatch
LiveFlow._ask_agent to return canned lines, so we can assert the state ladder
intro -> project -> project_qa -> knowledge -> role -> coding -> wrap -> done, that
each state advances by its turn budget, and that each round records an answer + a
PlannedQuestion for scoring. A separate test exercises the prompt-building
(identity/resume/requirements/full-history) as string content rather than a live
network call.
"""

from __future__ import annotations

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
from agent.liveflow import LiveFlow, STATES


def _make_ctx(has_coding: bool = True) -> InterviewContext:
    sections = ["intro", "behavioral", "technical", "coding", "wrap"] if has_coding else ["intro", "behavioral", "technical", "wrap"]
    plan = QuestionPlan(
        sections_order=sections,
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
    assert flow.state == "intro"


def test_state_machine_reaches_every_state_then_done(monkeypatch):
    """With turn budgets of 1, the machine walks each state and finishes."""
    ctx = _make_ctx(has_coding=True)
    budgets = {s: 1 for s in STATES}
    flow = LiveFlow(ctx, turn_budgets=budgets)

    def fake_ask(_self):
        return {
            "intro": "请自我介绍。",
            "project": "请介绍项目A。",
            "project_qa": "项目有什么难点？",
            "knowledge": "你熟悉什么基础/知识？",
            "role": "你为什么想来这个岗位？",
            "coding": "请开始写代码。",
            "wrap": "感谢，再见。",
        }[flow.state]

    monkeypatch.setattr(LiveFlow, "_ask_agent", fake_ask)
    flow.opening_line()
    visited = []
    for _ in range(20):
        flow.next_line("这是我的回答。")
        visited.append(flow.state if not flow.done else None)
        if flow.done:
            break
    # We must pass through every state (a deterministic ladder).
    assert "project" in visited
    assert "project_qa" in visited
    assert "knowledge" in visited
    assert "role" in visited
    assert "coding" in visited
    assert None in visited  # ended
    assert flow.done


def test_no_coding_skips_to_wrap_and_never_enters_coding(monkeypatch):
    ctx = _make_ctx(has_coding=False)
    budgets = {s: 1 for s in STATES}
    flow = LiveFlow(ctx, has_coding=False, turn_budgets=budgets)

    monkeypatch.setattr(LiveFlow, "_ask_agent", lambda _self: "好的，请继续。")
    flow.opening_line()
    visited = []
    for _ in range(12):
        flow.next_line("回答。")
        visited.append(flow.state)
        if flow.done:
            break
    assert "coding" not in visited
    assert "wrap" in visited
    assert flow.done


def test_larger_budget_keeps_state_until_answered_enough(monkeypatch):
    # project_qa budget=3: the state stays project_qa until 3 answers are given.
    ctx = _make_ctx()
    budgets = {s: 1 for s in STATES}
    budgets["project_qa"] = 3
    flow = LiveFlow(ctx, turn_budgets=budgets)
    monkeypatch.setattr(LiveFlow, "_ask_agent", lambda _self: "追问。")

    flow.opening_line()
    flow.next_line("答1")  # -> project
    flow.next_line("答2")  # -> project_qa
    assert flow.state == "project_qa"
    flow.next_line("答3")  # project_qa answer 1
    assert flow.state == "project_qa"
    flow.next_line("答4")  # project_qa answer 2
    assert flow.state == "project_qa"
    flow.next_line("答5")  # project_qa answer 3 -> advances
    assert flow.state != "project_qa"


def test_each_round_records_answer_and_question_for_scoring(monkeypatch):
    ctx = _make_ctx()
    flow = LiveFlow(ctx, turn_budgets={s: 1 for s in STATES})
    monkeypatch.setattr(LiveFlow, "_ask_agent", lambda _self: "这是问题。")

    flow.opening_line()
    before_q = len(ctx.plan.questions)
    before_a = len(ctx.answers)
    flow.next_line("这是回答。")
    assert len(ctx.plan.questions) == before_q + 1
    assert len(ctx.answers) == before_a + 1
    assert ctx.answers[-1].transcript == "这是回答。"


def test_answer_tagged_with_the_question_state_not_advanced_state(monkeypatch):
    """The answer to the intro question must be section intro, not the advanced state."""
    ctx = _make_ctx()
    flow = LiveFlow(ctx, turn_budgets={s: 1 for s in STATES})
    monkeypatch.setattr(LiveFlow, "_ask_agent", lambda _self: "请介绍项目。")

    flow.opening_line()  # asks intro question
    flow.next_line("我叫张三。")  # answers intro -> advances to project
    # The recorded planned question for this answer must be tagged intro.
    last_q = ctx.plan.questions[-1]
    assert last_q.section == "intro"
    assert last_q.target_competency == "intro"


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

    import agent.liveflow as lf
    monkeypatch.setattr(lf, "LLM", lambda: type("L", (), {"chat": fake_chat, "chat_json": lambda *a, **k: {}})())

    flow.turns = [{"role": "assistant", "content": "请自我介绍。"}, {"role": "user", "content": "我叫张三。"}]
    line = flow._ask_agent()
    assert line == "继续。"
    sys = captured["system"]
    assert "面试官" in sys  # identity
    assert "张三" in sys and "后端开发" in sys  # resume
    assert "字节" in sys and "重点考察算法" in sys  # requirements
    assert "我叫张三" in captured["user"] and "请自我介绍" in (captured["user"] or "")
