"""Prep phase: resume + JD + company + position => InterviewContext
(CandidateProfile / JobSpec / CompanyIntel / GapAnalysis / QuestionPlan).

Robustness contract (from adversarial review H1-H3): build_plan MUST NOT crash on
LLM network failure, non-JSON, or malformed-but-parseable JSON; things degrade to
best-effort fallbacks. CompanyIntel uses the Researcher hub (a Pydantic JobProfile)
via .model_dump(); if unavailable it falls back to an unknown-company intel."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import (
    CandidateProfile,
    CodingTendency,
    CompanyIntel,
    GapAnalysis,
    InterviewContext,
    InterviewerOS,
    JobSpec,
    MissingSlot,
    PlannedQuestion,
    QuestionPlan,
    RubricItem,
    Scorecard,
    ScoreItem,
    Source,
)
from .llm import LLM

SECTIONS = ["intro", "behavioral", "technical", "coding", "wrap"]

_PROBLEMS: list[dict] | None = None


def _load_problems() -> list[dict]:
    global _PROBLEMS
    if _PROBLEMS is not None:
        return _PROBLEMS
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent / "data" / "problems.json"
    try:
        d = json.loads(path.read_text())
        _PROBLEMS = d.get("problems", d) if isinstance(d, dict) else d
    except Exception:
        _PROBLEMS = []
    return _PROBLEMS


def pick_problem(topics: list[str] | None = None) -> dict | None:
    probs = _load_problems()
    if not probs:
        return None
    if topics:
        tl = {t.lower() for t in topics}
        for p in probs:
            if any(ts in tl or ts.lower() in tl for ts in p.get("topic_slugs", [])):
                return p
    import random
    return random.choice(probs)


# ---------------------------------------------------------------------------
# robust JSON + coercion helpers
# ---------------------------------------------------------------------------
def _as_str_list(x: Any) -> list[str]:
    if isinstance(x, list):
        return [str(v) for v in x if v is not None]
    if isinstance(x, str):
        return [x]
    return []


def _enum(value: Any, allowed: set[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _json_or(llm: LLM, system: str, user: str, default: dict, retries: int = 2, max_tokens: int = 2048) -> dict:
    for _ in range(retries):
        try:
            return llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=max_tokens)
        except Exception:
            continue
    return default


def _extract_candidate(llm: LLM, resume_text: str) -> CandidateProfile:
    sys_ = ("You extract a compact candidate profile. Return ONLY JSON matching: "
            "{name,headline,summary,skills[],experience[{company,role,duration,bullets[]}],"
            "projects[{name,role,bullets[]}],level(junior|mid|senior|staff),resume_hash}")
    j = _json_or(llm, sys_, f"Resume:\n{resume_text[:6000]}", {}, retries=2)
    try:
        exp = []
        for e in j.get("experience", []) if isinstance(j.get("experience"), list) else []:
            if isinstance(e, dict):
                exp.append({"company": str(e.get("company", "")), "role": str(e.get("role", "")),
                            "duration": str(e.get("duration", "")), "bullets": _as_str_list(e.get("bullets"))})
        proj = []
        for e in j.get("projects", []) if isinstance(j.get("projects"), list) else []:
            if isinstance(e, dict):
                proj.append({"name": str(e.get("name", "")), "role": str(e.get("role", "")), "bullets": _as_str_list(e.get("bullets"))})
        return CandidateProfile(
            name=str(j.get("name", "候选人") or "候选人"),
            headline=str(j.get("headline", "")),
            summary=str(j.get("summary", ""))[:1000],
            skills=_as_str_list(j.get("skills")),
            experience=exp,
            projects=proj,
            level=_enum(j.get("level"), {"junior", "mid", "senior", "staff"}, "mid"),
            resume_hash=hashlib.md5(resume_text[:200].encode("utf-8", "ignore")).hexdigest()[:16],
        )
    except Exception:
        return CandidateProfile(name="候选人", headline="", summary=resume_text[:300], skills=[],
                                experience=[], projects=[], level="mid",
                                resume_hash=hashlib.md5(resume_text[:200].encode("utf-8", "ignore")).hexdigest()[:16])


def _extract_job(llm: LLM, jd_text: str, company: str, position: str, seniority: str) -> JobSpec:
    sys_ = ("You extract a job spec. Return ONLY JSON matching: "
            "{position,seniority(junior|mid|senior|staff),company,must_have[],nice_to_have[],tech_stack[],"
            "responsibilities[],jd_text}")
    j = _json_or(llm, sys_, f"Company: {company}\nPosition: {position}\nSeniority: {seniority}\nJD:\n{jd_text[:6000]}", {})
    return JobSpec(
        position=str(j.get("position", position) or position),
        seniority=_enum(j.get("seniority"), {"junior", "mid", "senior", "staff"}, seniority),
        company=str(j.get("company", company) or company),
        must_have=_as_str_list(j.get("must_have")),
        nice_to_have=_as_str_list(j.get("nice_to_have")),
        tech_stack=_as_str_list(j.get("tech_stack")),
        responsibilities=_as_str_list(j.get("responsibilities")),
        jd_text=jd_text,
    )


def _fallback_company(company: str, job: JobSpec) -> CompanyIntel:
    return CompanyIntel(
        summary=f"{company} 后端/算法岗位。",
        tech_stack=job.tech_stack,
        values=[],
        interview_process="",
        recent_news=[],
        culture_notes="",
        coding_tendency=CodingTendency(prefers_live_coding=True, high_freq_topics=[], platform="leetcode"),
        missing_company_info=True,
        sources=[],
    )


def _company_from_profile(prof: Any) -> CompanyIntel | None:
    """Researcher returns a Pydantic JobProfile; consume via model_dump()."""
    if prof is None:
        return None
    try:
        d = prof.model_dump() if hasattr(prof, "model_dump") else prof
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    cp = d.get("company_profile", {}) if isinstance(d.get("company_profile"), dict) else {}
    ct = d.get("coding_tendency", {}) if isinstance(d.get("coding_tendency"), dict) else {}
    return CompanyIntel(
        summary=str(d.get("summary", "") or ""),
        tech_stack=_as_str_list(d.get("tech_stack")),
        values=_as_str_list(cp.get("values")),
        interview_process=str(cp.get("interview_process", "") or ""),
        recent_news=_as_str_list(cp.get("recent_news")),
        culture_notes=str(cp.get("culture_notes", "") or ""),
        coding_tendency=CodingTendency(
            prefers_live_coding=bool(ct.get("prefers_live_coding", True)),
            high_freq_topics=_as_str_list(ct.get("high_freq_topics")),
            platform=_enum(ct.get("platform"), {"leetcode", "coderpad", "local", "unknown"}, "leetcode"),
        ),
        missing_company_info=bool(d.get("missing_company_info", True)),
        sources=[Source(**s) for s in d.get("sources", []) if isinstance(s, dict)] or [],
    )


def _build_plan(llm: LLM, job: JobSpec, gap: GapAnalysis, company: CompanyIntel, lang: str, position: str) -> QuestionPlan:
    sys_ = ("You are a senior interviewer writing a mock-interview plan. Given the job/gap/company, produce 8-12 "
            "questions across sections in this order: intro, behavioral, technical, coding, wrap. Difficulty rises "
            "1->5. Each question: {id,section,text,question,difficulty(1-5),rubric[{point,weight,weights sum to 1}],"
            "followups[],target_competency}. Coding section: include exactly one question with target_competency "
            "'hand-code'. Return ONLY JSON matching {sections_order[],questions[]}.")
    user = (f"Position: {job.position} ({job.seniority}) @ {job.company}\n"
            f"Must-have: {job.must_have}\nNice-to-have: {job.nice_to_have}\n"
            f"Tech stack: {job.tech_stack}\nStrengths: {gap.strengths} Gaps: {gap.gaps} "
            f"Probe targets: {gap.probe_targets}\nLanguage: {lang}")
    j = _json_or(llm, sys_, user, {}, max_tokens=4000)
    qs: list[PlannedQuestion] = []
    for i, raw in enumerate(j.get("questions", []) if isinstance(j.get("questions"), list) else []):
        if not isinstance(raw, dict):
            continue
        try:
            rubrics = []
            for r in raw.get("rubric", []) if isinstance(raw.get("rubric"), list) else []:
                if isinstance(r, dict):
                    try:
                        rubrics.append(RubricItem(point=str(r.get("point", "")), weight=float(r.get("weight", 1))))
                    except Exception:
                        continue
            if rubrics:
                tot = sum(r.weight for r in rubrics) or 1.0
                rubrics = [RubricItem(point=r.point, weight=round(r.weight / tot, 3)) for r in rubrics]
            qs.append(PlannedQuestion(
                id=f"q{i}",
                section=_enum(raw.get("section"), {"intro", "behavioral", "technical", "coding", "wrap"}, "technical"),
                text=str(raw.get("text", "") or raw.get("question", "")),
                difficulty=int(max(1, min(5, float(raw.get("difficulty", 3) or 3)))),
                rubric=rubrics or [RubricItem(point="covers topic", weight=1.0)],
                followups=_as_str_list(raw.get("followups")),
                target_competency=str(raw.get("target_competency", job.position) or position),
            ))
        except Exception:
            continue
    if not qs:
        fallback_text = f"请谈谈你在 {job.tech_stack[0] if job.tech_stack else '后端'} 方向的经验与一个具体项目。"
        qs = [PlannedQuestion(id="q0", section="technical", text=fallback_text, difficulty=2,
                              rubric=[RubricItem(point="depth", weight=1.0)], followups=[], target_competency=position)]
    sections_order = [s for s in SECTIONS if any(q.section == s for q in qs)] or ["technical"]
    return QuestionPlan(sections_order=sections_order, questions=qs)


def _fallback_plan(position: str) -> QuestionPlan:
    q = PlannedQuestion(id="q0", section="technical", text=f"请谈谈你在 {position or '该岗位'} 方向的经验与一个具体项目。",
                        difficulty=2, rubric=[RubricItem(point="depth", weight=1.0)], followups=[], target_competency=position or "technical")
    return QuestionPlan(sections_order=["technical"], questions=[q])


def build_plan(resume_text: str, jd_text: str, company: str, position: str, seniority: str, lang: str = "zh") -> InterviewContext:
    llm = LLM()
    position = position or "软件工程师"
    seniority = _enum(seniority, {"junior", "mid", "senior", "staff"}, "mid")

    candidate = _extract_candidate(llm, resume_text)
    job = _extract_job(llm, jd_text, company, position, seniority)

    company_intel = _fallback_company(company, job)
    try:
        from .researcher import build_job_profile  # type: ignore
        prof = build_job_profile(company, position, jd_text, seniority, lang)
        got = _company_from_profile(prof)
        if got is not None:
            company_intel = got
    except Exception:
        pass  # fallback company_intel stands

    try:
        g = _json_or(llm, "Return ONLY JSON: {strengths[],gaps[],probe_targets[],missing_skills[]}",
                     f"Candidate: {candidate.summary}\nSkills: {candidate.skills}\nJob must-have: {job.must_have}", {})
        gap = GapAnalysis(strengths=_as_str_list(g.get("strengths")), gaps=_as_str_list(g.get("gaps")),
                          probe_targets=_as_str_list(g.get("probe_targets")), missing_skills=_as_str_list(g.get("missing_skills")))
    except Exception:
        gap = GapAnalysis(strengths=candidate.skills, gaps=[], probe_targets=candidate.projects[:2] or [], missing_skills=[])

    try:
        plan = _build_plan(llm, job, gap, company_intel, lang, position)
    except Exception:
        plan = _fallback_plan(position)

    for q in plan.questions:
        if q.section == "coding" and not q.problem_id:
            prob = pick_problem(job.tech_stack or [])
            if prob:
                q.problem_id = prob.get("title_slug")

    scorecard = Scorecard(overall=0, items=[], summary="", next_steps=[], model_answers=[],
                          interviewer_os=InterviewerOS(hidden_concern="", why_this_question=[], missing_slots=[], risk_level="low"))
    return InterviewContext(candidate=candidate, job=job, company=company_intel, gap=gap,
                            plan=plan, cursor=0, answers=[], scorecard=scorecard, status="prep")
