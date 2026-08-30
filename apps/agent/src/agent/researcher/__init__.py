"""Researcher module: web research + LLM synthesis -> structured JobProfile.

Public API::

    from agent.researcher import build_job_profile
    profile = build_job_profile("字节跳动", "后端开发工程师", "负责…", "senior", "zh")
"""

from .models import CompanyProfile, JobProfile, LikelyQuestion
from .profile import build_job_profile, fallback_profile
from .providers import (
    NowcoderProvider,
    SearchEngineProvider,
    SearchProvider,
    TavilyProvider,
    XiaohongshuProvider,
    ZhihuProvider,
    get_providers,
)

__all__ = [
    "JobProfile",
    "CompanyProfile",
    "LikelyQuestion",
    "build_job_profile",
    "fallback_profile",
    "SearchProvider",
    "SearchEngineProvider",
    "NowcoderProvider",
    "TavilyProvider",
    "XiaohongshuProvider",
    "ZhihuProvider",
    "get_providers",
]
