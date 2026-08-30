"""Prep phase: resume + JD + company + position => InterviewContext
(CandidateProfile / JobSpec / CompanyIntel / GapAnalysis / QuestionPlan).

Each extraction is a schema-constrained DeepSeek JSON call; failures degrade to
best-effort fallbacks so prep never crashes. CompanyIntel uses the Researcher
hub when available, else a "unknown company" fallback."""

from __future__ import annotations

import hashlib

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
    """Load the offline hand-code problem bank (title_slug keyed). Lazy + cached."""
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
    """Pick a bank problem, preferring a topic match to the job's tech stack."""
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


def _json(llm: LLM, system: str, user: str, retry: bool = True) -> dict:
    try:
        return llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}])
    except Exception:
        if retry:
            return llm.chat_json([{"role": "system", "content": system + " Reply with ONLY valid JSON."},
                                  {"role": "user", "content": user}])
        raise


def _extract_candidate(llm: LLM, resume_text: str) -> CandidateProfile:
    system = ("You extract a compact candidate profile for a technical interview. Return ONLY JSON matching: "
              "{name,headline,summary(<=120 chars),skills[list],experience[{company,role,duration,bullets[]}],"
              "projects[{name,role,bullets[]}],level(junior|mid|senior|staff),resume_hash}")
    j = _json(llm, system, f"Resume:\n{resume_text[:6000]}")
    return CandidateProfile(
        name=j.get("name", "Candidate"),
        headline=j.get("headline", ""),
        summary=j.get("summary", "")[:1000],
        skills=[str(s) for s in j.get("skills", [])],
        experience=j.get("experience", []) or [],
        projects=j.get("projects", []) or [],
        level=j.get("level", "mid"),
        resume_hash=hashlib.md5(resume_text[:200].encode("utf-8", "ignore")).hexdigest()[:16],
    )


def _extract_job(llm: LLM, jd_text: str, company: str, position: str, seniority: str) -> JobSpec:
    system = ("You extract a job spec. Return ONLY JSON matching: "
              "{position,seniority(junior|mid|senior|staff),company,must_have[],nice_to_have[],tech_stack[],"
              "responsibilities[],jd_text}")
    j = _json(llm, system, f"Company: {company}\nPosition: {position}\nSeniority: {seniority}\nJD:\n{jd_text[:6000]}")
    return JobSpec(
        position=j.get("position", position),
        seniority=j.get("seniority", seniority),
        company=j.get("company", company),
        must_have=[str(s) for s in j.get("must_have", [])],
        nice_to_have=[str(s) for s in j.get("nice_to_have", [])],
        tech_stack=[str(s) for s in j.get("tech_stack", [])],
        responsibilities=[str(s) for s in j.get("responsibilities", [])],
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


def _build_plan(llm: LLM, job: JobSpec, gap: GapAnalysis, company: CompanyIntel, lang: str) -> QuestionPlan:
    system = (
        "You are a senior interviewer writing a mock-interview plan. Given the job/gap/company, produce a plan of "
        "8-12 questions across sections in this order: intro, behavioral, technical, coding, wrap. Difficulty rises "
        "1->5. Each question: {id,section,text(one focused question, in the target language),difficulty(1-5),"
        "rubric[{point,weight(weights sum to 1)}],followups[],target_competency(short skill)}. "
        "For the 'coding' section include exactly one entry and set target_competency to 'hand-code'. "
        "Return ONLY JSON matching {sections_order[],questions[]}."
    )
    user = (f"Position: {job.position} ({job.seniority}) @ {job.company}\n"
            f"Must-have: {job.must_have}\nNice-to-have: {job.nice_to_have}\n"
            f"Tech stack: {job.tech_stack}\nResponsibilities: {job.responsibilities}\n"
            f"Strengths: {gap.strengths} Gaps: {gap.gaps} Probe targets: {gap.probe_targets}\n"
            f"Interview process note: {company.interview_process}\nLanguage: {lang}")
    j = _json(llm, system, user)
    qs = []
    for i, raw in enumerate(j.get("questions", [])):
        try:
            rubrics = [RubricItem(point=str(r.get("point", "")), weight=float(r.get("weight", 1))) for r in raw.get("rubric", [])]
            if rubrics:
                tot = sum(r.weight for r in rubrics)
                rubrics = [RubricItem(point=r.point, weight=round(r.weight / tot, 3)) for r in rubrics]
            qs.append(PlannedQuestion(
                id=f"q{i}",
                section=raw.get("section", "technical"),
                text=str(raw.get("text", "")),
                difficulty=int(max(1, min(5, float(raw.get("difficulty", 3))))),
                rubric=rubrics or [RubricItem(point="covers topic", weight=1.0)],
                followups=[str(f) for f in raw.get("followups", [])],
                target_competency=str(raw.get("target_competency", job.position)),
            ))
        except Exception:
            continue
    if not qs:
        qs = [PlannedQuestion(id="q0", section="technical", text=f"Tell me about your experience with {job.tech_stack[0] if job.tech_stack else 'backend'}.",
                              difficulty=2, rubric=[RubricItem(point="depth", weight=1.0)], followups=[], target_competency=job.position)]
    sections_order = [s for s in SECTIONS if any(q.section == s for q in qs)] or ["technical"]
    return QuestionPlan(sections_order=sections_order, questions=qs)


def build_plan(resume_text: str, jd_text: str, company: str, position: str, seniority: str, lang: str = "zh") -> InterviewContext:
    llm = LLM()
    candidate = _extract_candidate(llm, resume_text)
    job = _extract_job(llm, jd_text, company, position, seniority)
    # CompanyIntel via Researcher hub (available later); degrade gracefully now
    company_intel = _fallback_company(company, job)
    try:
        from .researcher import build_job_profile  # type: ignore
        prof = build_job_profile(company, position, jd_text, seniority, lang)
        company_intel = CompanyIntel(
            summary=prof.get("summary", company_intel.summary),
            tech_stack=prof.get("tech_stack", job.tech_stack),
            values=prof.get("company_profile", {}).get("values", []),
            interview_process=prof.get("company_profile", {}).get("interview_process", ""),
            recent_news=prof.get("company_profile", {}).get("recent_news", []),
            culture_notes=prof.get("company_profile", {}).get("culture_notes", ""),
            coding_tendency=CodingTendency(
                prefers_live_coding=prof.get("coding_tendency", {}).get("prefers_live_coding", True),
                high_freq_topics=prof.get("coding_tendency", {}).get("high_freq_topics", []),
                platform=prof.get("coding_tendency", {}).get("platform", "leetcode"),
            ),
            missing_company_info=bool(prof.get("missing_company_info", True)),
            sources=[Source(**s) for s in prof.get("sources", [])] if prof.get("sources") else [],
        )
    except Exception:
        pass  # fallback company_intel stands

    # gap analysis
    try:
        g = _json(llm, "Return ONLY JSON: {strengths[],gaps[],probe_targets[],missing_skills[]}",
                  f"Candidate: {candidate.summary}\nSkills: {candidate.skills}\nJob must-have: {job.must_have}")
        gap = GapAnalysis(strengths=[str(x) for x in g.get("strengths", [])],
                          gaps=[str(x) for x in g.get("gaps", [])],
                          probe_targets=[str(x) for x in g.get("probe_targets", [])],
                          missing_skills=[str(x) for x in g.get("missing_skills", [])])
    except Exception:
        gap = GapAnalysis(strengths=candidate.skills, gaps=[], probe_targets=candidate.projects[:2], missing_skills=[])

    plan = _build_plan(llm, job, gap, company_intel, lang)
    # attach a real offline problem to the coding round (for the hand-code persona)
    for q in plan.questions:
        if q.section == "coding" and not q.problem_id:
            prob = pick_problem(job.tech_stack or [])
            if prob:
                q.problem_id = prob.get("title_slug")
    scorecard = Scorecard(overall=0, items=[], summary="", next_steps=[], model_answers=[],
                          interviewer_os=InterviewerOS(hidden_concern="", why_this_question=[], missing_slots=[], risk_level="low"))
    return InterviewContext(candidate=candidate, job=job, company=company_intel, gap=gap,
                            plan=plan, cursor=0, answers=[], scorecard=scorecard, status="prep")
