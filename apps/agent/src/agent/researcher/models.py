"""Pydantic models for the Researcher module.

``JobProfile`` is the structured output of :func:`agent.researcher.profile.build_job_profile`.
It reuses the shared contracts (``Source``, ``CodingTendency``) from
``agent.contracts`` so downstream agents can consume it directly.
"""

from pydantic import BaseModel, Field

from agent.contracts import CodingTendency, Source


def _default_coding_tendency() -> CodingTendency:
    """CodingTendency has two required fields; give them honest defaults."""
    return CodingTendency(prefers_live_coding=False, high_freq_topics=[])


class LikelyQuestion(BaseModel):
    """A likely interview question for this job, with provenance + frequency."""

    question: str
    topic: str = ""
    #: web = found in search results / knowledge = interviewer-knowledge based
    source: str = "knowledge"
    #: high | medium | low
    frequency: str = "medium"


class CompanyProfile(BaseModel):
    """What the interviewer should know about the target company."""

    industry: str = ""
    values: list[str] = Field(default_factory=list)
    interview_process: str = ""
    recent_news: list[str] = Field(default_factory=list)
    culture_notes: str = ""


class JobProfile(BaseModel):
    """Structured research output for (company, position, seniority).

    ``missing_company_info=True`` is an *honest* signal: the researcher could not
    find company-specific information and refuses to fabricate it.
    """

    position: str
    company: str
    seniority: str = "mid"
    language: str = "zh"
    summary: str = ""
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    interview_focus: list[str] = Field(default_factory=list)
    likely_questions: list[LikelyQuestion] = Field(default_factory=list)
    coding_tendency: CodingTendency = Field(default_factory=_default_coding_tendency)
    company_profile: CompanyProfile = Field(default_factory=CompanyProfile)
    missing_company_info: bool = True
    sources: list[Source] = Field(default_factory=list)
    #: 0.0..1.0 self-assessed confidence of this profile
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
