"""Pydantic contracts mirroring packages/shared (zod). One source of truth in
packages/shared/src/index.ts; keep these in sync (see docs/开发流程-迭代起点.md)."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Source(BaseModel):
    title: str
    url: str
    snippet: str
    provider: str = Field(
        "search-engine",
        pattern="^(search-engine|nowcoder|xiaohongshu|zhihu|tavily|playbook)$",
    )


class ExperienceItem(BaseModel):
    company: str
    role: str
    duration: str
    bullets: list[str]


class ProjectItem(BaseModel):
    name: str
    role: str
    bullets: list[str]


class CandidateProfile(BaseModel):
    name: str
    headline: str
    summary: str
    skills: list[str]
    experience: list[ExperienceItem]
    projects: list[ProjectItem]
    level: str = Field(pattern="^(junior|mid|senior|staff)$")
    resume_hash: str


class JobSpec(BaseModel):
    position: str
    seniority: str = Field(pattern="^(junior|mid|senior|staff)$")
    company: str
    must_have: list[str]
    nice_to_have: list[str]
    tech_stack: list[str]
    responsibilities: list[str]
    jd_text: str


class CodingTendency(BaseModel):
    prefers_live_coding: bool
    high_freq_topics: list[str]
    platform: str = Field("unknown", pattern="^(leetcode|coderpad|local|unknown)$")


class CompanyIntel(BaseModel):
    summary: str
    tech_stack: list[str]
    values: list[str]
    interview_process: str
    recent_news: list[str]
    culture_notes: str
    coding_tendency: CodingTendency
    missing_company_info: bool
    sources: list[Source]


class GapAnalysis(BaseModel):
    strengths: list[str]
    gaps: list[str]
    probe_targets: list[str]
    missing_skills: list[str]


class RubricItem(BaseModel):
    point: str
    weight: float


class PlannedQuestion(BaseModel):
    id: str
    section: str = Field(pattern="^(intro|behavioral|technical|coding|wrap)$")
    text: str
    difficulty: int = Field(ge=1, le=5)
    rubric: list[RubricItem]
    followups: list[str]
    target_competency: str
    problem_id: Optional[str] = None


class QuestionPlan(BaseModel):
    sections_order: list[str]
    questions: list[PlannedQuestion]


class ScoreItem(BaseModel):
    competency: str
    score: float = Field(ge=0, le=5)
    evidence: str
    level: str = Field(pattern="^(below|meets|exceeds)$")


class AnswerRecord(BaseModel):
    question_id: str
    transcript: str
    score: Optional[float] = Field(default=None, ge=0, le=5)
    status: str = Field(pattern="^(asked|answered|skipped)$")
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    final_code: Optional[str] = None
    # --- coding-round signals (used by post report, not during live) ---
    coding_status: Optional[str] = Field(default=None, pattern="^(correct|partial|incorrect|incomplete)$")
    hint_level: Optional[int] = None
    passed_tests: Optional[int] = None
    total_tests: Optional[int] = None


class MissingSlot(BaseModel):
    slot: str
    evidence: str
    why_it_matters: str
    what_i_want_to_hear: list[str]
    one_line_advice: str


class InterviewerOS(BaseModel):
    hidden_concern: str
    why_this_question: list[str]
    missing_slots: list[MissingSlot]
    risk_level: str = Field(pattern="^(low|medium|high)$")


class Scorecard(BaseModel):
    overall: float = Field(ge=0, le=100)
    items: list[ScoreItem]
    summary: str
    next_steps: list[str]
    model_answers: list[str]
    interviewer_os: InterviewerOS


class InterviewContext(BaseModel):
    candidate: CandidateProfile
    job: JobSpec
    company: CompanyIntel
    gap: GapAnalysis
    plan: QuestionPlan
    cursor: int = 0
    answers: list[AnswerRecord] = []
    scorecard: Scorecard
    status: str = Field("prep", pattern="^(prep|live|post|complete)$")
