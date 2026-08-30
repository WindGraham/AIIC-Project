"""Job-profile synthesis: providers + LLM -> structured :class:`JobProfile`.

Flow (DeepInterview-style prep, mock-first / no hard state machine):

1. 90-day cache check (key = company|position|seniority) -> hit returns directly.
2. Run keyless + optional providers in parallel (bounded by a deadline).
3. LLM ``chat_json`` synthesis with the collected sources.
4. Schema validation failure -> one compact retry -> static ``fallback_profile``.
5. Never raises. Honest ``missing_company_info`` / low ``confidence`` when the
   web yielded nothing company-specific.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

from agent.config import get_settings
from agent.contracts import CodingTendency, Source
from agent.llm import LLM

from .models import CompanyProfile, JobProfile, LikelyQuestion
from .providers import count_company_hits, get_providers, run_queries

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = 90

# --- query templates (position / company / 面经), MockMate-inspired ----------
QUERY_TEMPLATES_ZH = {
    "jobs": [
        "{position} 岗位要求 技能要求",
        "{position} JD 职位描述 任职要求",
        "{position} 技术栈 职责",
    ],
    "interviews": [
        "{position} 面经 面试经验",
        "{position} 面试题 高频 考察",
        "{position} 面试 知乎 经验",
    ],
    "company_jobs": [
        "{company} {position} 招聘 岗位职责",
        "{company} {position} JD 任职要求",
    ],
    "company_interviews": [
        "{company} {position} 面经 面试经验",
        "{company} {position} 面试风格 几轮",
        "{company} 面试 算法 考察",
    ],
}
QUERY_TEMPLATES_EN = {
    "jobs": [
        "{position} job requirements skills",
        "{position} JD job description requirements",
    ],
    "interviews": [
        "{position} interview questions experience",
        "{position} interview process",
    ],
    "company_jobs": [
        "{company} {position} job openings requirements",
        "{company} {position} JD",
    ],
    "company_interviews": [
        "{company} {position} interview experience",
        "{company} interview process rounds",
    ],
}


def _build_queries(company: str, position: str, language: str) -> list[str]:
    templates = QUERY_TEMPLATES_ZH if language == "zh" else QUERY_TEMPLATES_EN
    queries: list[str] = []
    # company-specific categories first so their results are submitted earliest
    for category in ("company_interviews", "company_jobs", "interviews", "jobs"):
        for t in templates[category]:
            q = t.replace("{position}", position).replace("{company}", company).strip()
            if q and q not in queries:
                queries.append(q)
    return queries[:14]  # bound total query count


# --- cache -------------------------------------------------------------------
def _cache_path() -> Path:
    override = os.environ.get("RESEARCHER_CACHE_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent / "researcher_cache.json"


def _cache_key(company: str, position: str, seniority: str) -> str:
    return "|".join(x.strip() for x in (company, position, seniority))


def _load_cache() -> dict:
    try:
        p = _cache_path()
        if not p.exists():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("researcher: cache load failed: %s", exc)
        return {}


def _save_cache(cache: dict) -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("researcher: cache save failed: %s", exc)


def _cache_lookup(key: str) -> Optional[JobProfile]:
    cache = _load_cache()
    entry = cache.get(key)
    if not entry:
        return None
    try:
        ts = entry.get("ts", 0)
        if time.time() - ts > CACHE_TTL_DAYS * 86400:
            return None
        return JobProfile.model_validate(entry["profile"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("researcher: cache entry invalid: %s", exc)
        return None


def _cache_store(key: str, profile: JobProfile) -> None:
    cache = _load_cache()
    cache[key] = {"ts": time.time(), "profile": profile.model_dump(mode="json")}
    # prune expired keys opportunistically
    now = time.time()
    for k in list(cache.keys()):
        try:
            if now - cache[k]["ts"] > CACHE_TTL_DAYS * 86400:
                del cache[k]
        except Exception:
            cache.pop(k, None)
    _save_cache(cache)


# --- LLM prompts --------------------------------------------------------------
def _build_synth_prompt(
    company: str,
    position: str,
    seniority: str,
    jd: str,
    language: str,
    sources: list[Source],
    compact: bool,
) -> list[dict]:
    lang_label = "中文" if language == "zh" else "English"
    jd_block = ""
    if jd and not compact:
        jd_block = f"\n岗位描述(JD)：\n{jd[:2000]}\n"
    src_block = ""
    if sources:
        shown = sources[:10] if compact else sources[:30]
        lines = [f"- [{s.title}] {s.snippet} ({s.url})" for s in shown if s.title]
        if lines:
            src_block = "\n=== 网络搜索结果（可能为空/不完整，仅供参考）===\n" + "\n".join(lines)
    system = (
        "你是资深的技术招聘研究员，为 AI 模拟面试官平台生成目标岗位的结构化画像。"
        "只输出一个合法 JSON 对象，不要输出解释、思考过程或代码块。"
        "必须诚实：查不到的公司专属信息不要编造。"
    )
    user = f"""目标公司：{company}
目标岗位：{position}
职级：{seniority}
输出语言：{lang_label}
{jd_block}
{src_block}

直接输出 JSON，必须包含且仅包含以下字段：
{{
  "position": "岗位名称",
  "company": "公司名称",
  "seniority": "{seniority}",
  "summary": "岗位概述（2-3 句话）",
  "required_skills": ["必备技能"],
  "nice_to_have": ["加分技能"],
  "tech_stack": ["核心技术"],
  "responsibilities": ["工作职责"],
  "interview_focus": ["面试重点考察方向（3-5 个）"],
  "likely_questions": [{{"question": "具体面试题", "topic": "考察点", "source": "web 或 knowledge", "frequency": "high 或 medium 或 low"}}],
  "coding_tendency": {{"prefers_live_coding": true, "high_freq_topics": ["高频算法/题型"], "platform": "leetcode 或 coderpad 或 local 或 unknown"}},
  "company_profile": {{"industry": "行业", "values": ["价值观"], "interview_process": "面试流程（几轮、风格）", "recent_news": ["近期动态"], "culture_notes": "文化氛围备注"}},
  "missing_company_info": true,
  "confidence": 0.5
}}

要求：
- likely_questions 给出 5-8 道该岗位（{position} @ {company}）最可能被问到的真实题目；CS 算法/研发岗应包含算法题。
- coding_tendency.platform 只能是 leetcode/coderpad/local/unknown 之一。
- 若搜索结果为空或没有该公司专属信息，missing_company_info 必须为 true，company_profile 相关字段留空或如实写"未查到"。
- confidence 是 0.0-1.0 的浮点数：搜索数据充分且公司相关 0.7-0.9；仅有通用知识 0.3-0.5；几乎无信息 0.1-0.2。
- 全部内容用{lang_label}填写。"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# --- fallback ----------------------------------------------------------------
_BACKEND_SKILLS = ["Java/Go/Python", "MySQL", "Redis", "Kafka/RocketMQ", "分布式系统", "操作系统", "网络", "算法与数据结构"]
_BACKEND_QUESTIONS = [
    ("进程、线程、协程的区别是什么？", "操作系统", "high"),
    ("MySQL 索引为什么用 B+ 树？", "数据库", "high"),
    ("Redis 的过期删除策略与内存淘汰机制", "缓存", "high"),
    ("如何设计一个支持高并发的秒杀系统？", "系统设计", "medium"),
    ("TCP 三次握手与四次挥手，为什么？", "网络", "high"),
    ("消息队列如何保证消息不丢失/不重复？", "消息中间件", "medium"),
    ("算法题：LRU 缓存实现", "算法", "high"),
    ("算法题：Top K 问题", "算法", "medium"),
]
_ALGO_SKILLS = ["Python/C++", "机器学习", "深度学习", "数据结构与算法", "PyTorch", "特征工程", "模型评估"]
_ALGO_QUESTIONS = [
    ("手撕：快排/归并/堆排序并分析复杂度", "算法", "high"),
    ("手撕：二叉树层序遍历/最近公共祖先", "算法", "high"),
    ("Transformer 的 self-attention 复杂度为什么是 O(n²)？", "深度学习", "high"),
    ("如何解决样本不均衡问题？", "机器学习", "medium"),
    ("模型过拟合如何诊断与缓解？", "机器学习", "high"),
    ("如何评估一个推荐系统/搜索排序模型？", "评估", "medium"),
    ("手撕：二分查找变体 / 双指针题", "算法", "high"),
]
_FRONTEND_SKILLS = ["JavaScript/TypeScript", "React/Vue", "浏览器原理", "HTTP/网络", "工程化", "性能优化"]
_FRONTEND_QUESTIONS = [
    ("React 的虚拟 DOM 与 diff 原理", "框架", "high"),
    ("Vue 的响应式原理（Object.defineProperty vs Proxy）", "框架", "high"),
    ("浏览器从输入 URL 到页面渲染的完整过程", "浏览器", "high"),
    ("跨域方案有哪些？CORS 细节", "网络", "medium"),
    ("前端性能优化你做过哪些？如何量化？", "性能", "medium"),
    ("手写：深拷贝 / 防抖节流 / Promise.all", "手写题", "high"),
    ("HTTP/1.1、HTTP/2、HTTP/3 的区别", "网络", "medium"),
]
_GENERIC_QUESTIONS = [
    ("介绍一个你最有挑战的项目，难点与解决过程", "项目深挖", "high"),
    ("为什么选择我们公司和这个岗位？", "动机", "medium"),
    ("遇到线上故障如何排查？讲一个真实案例", "故障排查", "medium"),
    ("算法题：两数之和 / 反转链表", "算法", "high"),
    ("你的职业规划是什么？", "职业规划", "medium"),
]


def _static_profile(company: str, position: str, seniority: str, language: str) -> JobProfile:
    """Pure rule-based fallback (no LLM / no network). Honest about gaps."""
    pos = position or ""
    lower = pos.lower()
    if any(k in lower for k in ("后端", "服务端", "java", "go", "php", "c++", "server", "backend", "开发")):
        skills, questions = _BACKEND_SKILLS, _BACKEND_QUESTIONS
        focus = ["算法与数据结构", "语言/框架深度", "分布式与高并发", "数据库与缓存", "系统设计"]
    elif any(k in lower for k in ("算法", "推荐", "搜索", "nlp", "机器学习", "深度学习", "ai", "大模型", "数据")):
        skills, questions = _ALGO_SKILLS, _ALGO_QUESTIONS
        focus = ["算法与数据结构", "机器学习基础", "深度学习/LLM", "模型评估与优化", "工程落地"]
    elif any(k in lower for k in ("前端", "客户端", "ios", "android", "web", "frontend")):
        skills, questions = _FRONTEND_SKILLS, _FRONTEND_QUESTIONS
        focus = ["前端基础", "框架原理", "浏览器/网络", "工程化", "性能优化"]
    else:
        skills, questions = ["算法与数据结构", "核心语言", "计算机网络", "操作系统", "数据库"], _GENERIC_QUESTIONS
        focus = ["算法", "基础原理", "项目深挖", "行为面试"]

    likely = [
        LikelyQuestion(question=q, topic=t, source="playbook", frequency=f)
        for q, t, f in questions[:6]
    ]
    return JobProfile(
        position=position,
        company=company,
        seniority=seniority,
        language=language,
        summary=(
            f"基于内置知识库生成的{position or '该岗位'}画像（网络搜索不可用或未返回有效数据）。"
            "该岗位的面试通常覆盖基础原理、算法与项目深挖；以下为通用高频考察点，公司专属信息未能核实。"
        ),
        required_skills=skills[:6],
        nice_to_have=["开源项目", "高并发/大规模系统经验", "英语读写"],
        tech_stack=skills[:4],
        responsibilities=[
            f"负责{position or '相关'}系统的设计、开发与维护",
            "参与需求评审与技术方案设计",
            "持续优化系统性能与稳定性",
        ],
        interview_focus=focus,
        likely_questions=likely,
        coding_tendency=CodingTendency(
            prefers_live_coding=True,
            high_freq_topics=["数组/哈希表", "链表", "二叉树", "动态规划", "二分查找"],
            platform="unknown",
        ),
        company_profile=CompanyProfile(
            industry="",
            values=[],
            interview_process="未查到该公司面试流程信息",
            recent_news=[],
            culture_notes="未查到该公司文化信息",
        ),
        missing_company_info=True,
        sources=[
            Source(
                title="内置知识库兜底画像",
                url="",
                snippet="网络搜索不可用时基于静态 playbook/通用岗位知识生成，未核实公司专属信息。",
                provider="playbook",
            )
        ],
        confidence=0.15,
    )


def fallback_profile(
    company: str, position: str, jd: str = "", seniority: str = "mid", language: str = "zh", *, _llm: Optional[LLM] = None
) -> JobProfile:
    """Fallback path: try the LLM's own knowledge once, then the static playbook.

    Never raises — the static profile is the last resort.
    """
    llm = _llm or LLM()
    try:
        messages = _build_synth_prompt(company, position, seniority, jd, language, [], compact=True)
        data = llm.chat_json(messages, max_tokens=2048)
        profile = JobProfile.model_validate(data)
        profile.sources = []  # no web evidence
        profile.missing_company_info = True
        profile.confidence = min(profile.confidence, 0.3)
        profile.language = language
        return profile
    except Exception as exc:  # noqa: BLE001
        logger.warning("researcher: LLM-knowledge fallback failed (%s); using static playbook", exc)
        return _static_profile(company, position, seniority, language)


# --- main entry --------------------------------------------------------------
def build_job_profile(
    company: str,
    position: str,
    jd: str = "",
    seniority: str = "mid",
    language: str = "zh",
    *,
    force: bool = False,
    _llm: Optional[LLM] = None,
    _providers: Optional[list[SearchProvider]] = None,
) -> JobProfile:
    """Synthesize a :class:`JobProfile` for (company, position, seniority).

    Contract: **never raises**. On total failure it returns the static
    ``fallback_profile`` so the interview flow can always proceed.
    """
    company = (company or "").strip()
    position = (position or "").strip()
    seniority = (seniority or "mid").strip()
    key = _cache_key(company, position, seniority)

    if not force:
        cached = _cache_lookup(key)
        if cached is not None:
            logger.info("researcher: cache hit for %r", key)
            return cached

    llm = _llm or LLM()
    providers = _providers if _providers is not None else get_providers()

    # 1) search phase (bounded by deadline; failures already degrade to [])
    queries = _build_queries(company, position, language)
    logger.info("researcher: building profile for %s @ %s (seniority=%s, %d queries)",
                position, company, seniority, len(queries))
    sources = run_queries(
        providers,
        queries,
        per_query=8,
        max_total=40,
        deadline=35.0,
        require_company_hits=company,
    )
    company_hits = count_company_hits(sources, company)
    logger.info("researcher: collected %d sources (%d company-specific) for %s @ %s",
                len(sources), company_hits, position, company)

    # 2) LLM synthesis with schema validation; retry compact on failure
    profile: Optional[JobProfile] = None
    for compact in (False, True):
        try:
            messages = _build_synth_prompt(company, position, seniority, jd, language, sources, compact=compact)
            data = llm.chat_json(messages, max_tokens=4096 if not compact else 2048)
            candidate = JobProfile.model_validate(data)
            # 3) post-fix: real sources replace anything the LLM might have invented
            candidate.sources = sources[:30]
            if not company_hits:
                candidate.missing_company_info = True
                candidate.confidence = min(candidate.confidence, 0.3)
            candidate.confidence = max(0.0, min(1.0, candidate.confidence))
            profile = candidate
            break
        except Exception as exc:  # noqa: BLE001 - ValidationError / JSON / network
            logger.warning("researcher: LLM synthesis failed (compact=%s): %s", compact, exc)
            continue

    if profile is None:
        logger.warning("researcher: falling back to fallback_profile for %s @ %s", position, company)
        profile = fallback_profile(company, position, jd, seniority, language, _llm=llm)
        if sources:
            profile.sources = sources[:30]
            profile.missing_company_info = not company_hits

    _cache_store(key, profile)
    logger.info("researcher: profile ready for %s @ %s (confidence=%.2f, missing=%s, sources=%d)",
                position, company, profile.confidence, profile.missing_company_info, len(profile.sources))
    return profile
