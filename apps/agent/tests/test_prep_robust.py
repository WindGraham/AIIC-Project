"""Regression tests for the H1-H3 adversarial-review fixes in prep.py:
- build_plan must NOT crash when the LLM is down (H1)
- build_plan must NOT crash on malformed-but-parseable JSON (H2)
- Researcher (a Pydantic model) must be consumed via model_dump() (H3)

Run: cd apps/agent && .venv/bin/python -m pytest tests/test_prep_robust.py -v
"""

import pytest

from agent import prep as prep_mod


class FakeLLM:
    def __init__(self, mode: str):
        self.mode = mode

    def chat_json(self, messages, **kw):
        if self.mode == "raise":
            raise RuntimeError("LLM down")
        if self.mode == "bad":
            # malformed but parseable: bad enums, non-list where list expected,
            # bad difficulty, missing experience fields
            return {
                "name": "X", "headline": "h", "summary": "s", "skills": "python",
                "experience": [{"company": "c"}], "projects": [{"name": "p"}],
                "level": "principal",
                "position": "后端", "seniority": "mid", "company": "字节",
                "must_have": 123, "tech_stack": ["python"],
                "questions": [
                    {"id": "q0", "section": "technical", "text": "Q?", "difficulty": "abc",
                     "rubric": [{"point": "p", "weight": 1}], "followups": [], "target_competency": "t"}],
                "sections_order": ["technical"],
            }
        if self.mode == "ok":
            return {
                "name": "王五", "headline": "后端", "summary": "3年后端", "skills": ["python"],
                "experience": [], "projects": [], "level": "mid",
                "position": "后端", "seniority": "mid", "company": "字节",
                "must_have": ["python"], "nice_to_have": [], "tech_stack": ["python"], "responsibilities": [],
                "questions": [{"id": "q0", "section": "technical", "text": "自我介绍", "difficulty": 2,
                               "rubric": [{"point": "depth", "weight": 1}], "followups": [], "target_competency": "后端"}],
                "sections_order": ["technical"],
            }
        return {}


def _patch(monkeypatch, mode: str, researcher_return=None, researcher_raises: bool = True):
    monkeypatch.setattr(prep_mod, "LLM", lambda: FakeLLM(mode))
    import agent.researcher as R
    if researcher_raises:
        monkeypatch.setattr(R, "build_job_profile", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("search down")))
    else:
        monkeypatch.setattr(R, "build_job_profile", lambda *a, **k: researcher_return)


def test_llm_down_does_not_crash(monkeypatch):
    _patch(monkeypatch, "raise")
    ctx = prep_mod.build_plan("张三 3年后端", "后端JD", "字节", "后端开发工程师", "senior", "zh")
    assert ctx is not None
    assert len(ctx.plan.questions) >= 1
    assert ctx.scorecard is not None


def test_malformed_json_does_not_crash(monkeypatch):
    _patch(monkeypatch, "bad")
    ctx = prep_mod.build_plan("", "", "字节", "后端", "senior", "zh")
    assert ctx is not None
    assert len(ctx.plan.questions) >= 1


class FakeJobProfile:
    def model_dump(self):
        return {
            "summary": "字节后端岗位", "tech_stack": ["python"],
            "company_profile": {"values": ["坦诚"], "interview_process": "3轮"},
            "coding_tendency": {"prefers_live_coding": True, "platform": "leetcode", "high_freq_topics": ["数组"]},
            "missing_company_info": False,
            "sources": [{"title": "t", "url": "u", "snippet": "s", "provider": "nowcoder"}],
        }


def test_researcher_consumed_via_model_dump(monkeypatch):
    _patch(monkeypatch, "ok", researcher_return=FakeJobProfile(), researcher_raises=False)
    ctx = prep_mod.build_plan("张三 3年后端", "后端JD", "字节", "后端", "senior", "zh")
    assert ctx.company.missing_company_info is False
    assert ctx.company.tech_stack == ["python"]
    assert ctx.company.sources[0].provider == "nowcoder"
