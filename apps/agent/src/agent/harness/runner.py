"""runner — 从 regression/ 语料跑 N 场双 agent 互聊，产出并汇总回归数据。

每场产出 (transcript, scorecard, report, metrics) 存到 `harness/run_out/`
（默认相对 cwd 解析，即 `apps/agent/harness/run_out/`），并支持多场汇总对比。

真实 brain 就绪后传 `use_real_pipeline=True`：
    from agent.pipeline import run_interview_text
即无缝切换（找不到时自动降级回 mock_brain 并告警）。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from agent.contracts import (
    CandidateProfile,
    CodingTendency,
    CompanyIntel,
    ExperienceItem,
    GapAnalysis,
    InterviewContext,
    JobSpec,
    InterviewerOS,
    PlannedQuestion,
    ProjectItem,
    QuestionPlan,
    RubricItem,
    Scorecard,
    Source,
)
from agent.llm import LLM

from .candidate import CandidateAgent
from .judge import Judge
from .mock_brain import run_interview_text as _mock_run_interview_text
from .mock_brain import run_interview_text_with_log
from .regression.cases import CASES

DEFAULT_OUT_DIR = os.path.join("harness", "run_out")

# ---------------------------------------------------------------------------
# 默认空 scorecard（InterviewContext 构造需要）
# ---------------------------------------------------------------------------
def empty_scorecard() -> Scorecard:
    return Scorecard(
        overall=0.0,
        items=[],
        summary="",
        next_steps=[],
        model_answers=[],
        interviewer_os=InterviewerOS(
            hidden_concern="",
            why_this_question=[],
            missing_slots=[],
            risk_level="low",
        ),
    )


# ---------------------------------------------------------------------------
# Canned plan（确定性，默认路径） / LLM plan（chat_json + pydantic 校验，可选）
# ---------------------------------------------------------------------------
def _q(
    qid: str,
    section: str,
    text: str,
    difficulty: int,
    competency: str,
    rubric_points: list[str],
    followups: list[str],
    problem_id: str | None = None,
) -> PlannedQuestion:
    return PlannedQuestion(
        id=qid,
        section=section,
        text=text,
        difficulty=difficulty,
        rubric=[RubricItem(point=p, weight=round(1.0 / len(rubric_points), 2)) for p in rubric_points],
        followups=followups,
        target_competency=competency,
        problem_id=problem_id,
    )


_CODING_PROBLEMS = {
    "junior": {
        "title": "反转链表",
        "problem_id": "lc-206",
        "text": "手撕代码：反转一个单链表（迭代实现）。请先说明思路与时间复杂度，再写出代码。",
    },
    "mid": {
        "title": "LRU 缓存",
        "problem_id": "lc-146",
        "text": "手撕代码：实现 LRU 缓存（get/put 均 O(1)）。请先说明数据结构选型，再写出代码。",
    },
    "senior": {
        "title": "无重复字符的最长子串",
        "problem_id": "lc-003",
        "text": "手撕代码：给定字符串，求无重复字符的最长子串长度，要求 O(n)。请先讲思路再写代码。",
    },
}


def _canned_plan(case: dict[str, Any]) -> QuestionPlan:
    level = case.get("level", "mid")
    comp = case["company"]
    pos = case["position"]
    must_have = case.get("must_have", [])
    skill1 = must_have[0] if must_have else "核心技能"
    skill2 = must_have[1] if len(must_have) > 1 else "数据结构与算法"
    coding = _CODING_PROBLEMS.get(level, _CODING_PROBLEMS["mid"])
    return QuestionPlan(
        sections_order=["intro", "behavioral", "technical", "coding", "wrap"],
        questions=[
            _q(
                "q1", "intro", f"先简单介绍一下你自己，以及你为什么应聘{comp}的{pos}？",
                1, "自我介绍与动机",
                ["自我介绍有结构（教育/经历/亮点）", "求职动机具体可信（结合岗位与公司）", "与岗位的匹配点明确"],
                ["你对我们团队或业务了解多少？", "未来 1-2 年的职业规划是什么？"],
            ),
            _q(
                "q2", "behavioral", "讲一个你最有成就感或最有挑战的项目，你具体承担了什么角色、解决了什么问题？",
                2, "项目经历与个人贡献",
                ["角色与贡献具体清晰", "问题/方案/结果有闭环（STAR）", "有量化结果或明确改进"],
                ["项目里最棘手的一个技术难点是什么？", "如果重来一次，哪里会做得不一样？"],
            ),
            _q(
                "q3", "technical", f"你在项目/学习中用到过{skill1}，能结合一个实际场景讲讲它的典型用法和要注意的坑吗？",
                2, "技术深度（基础）",
                ["场景描述真实具体", "能讲清原理或选型原因", "能说出常见的坑与规避方式"],
                ["如果数据量再大一个数量级，你的方案还成立吗？", "还有哪些替代方案，你当时为什么没选？"],
            ),
            _q(
                "q4", "technical", f"假设让你设计一个与{skill2}相关的系统/模块，你会怎么做选型？主要权衡是什么？",
                3, "技术深度（设计）",
                ["能拆解需求与约束", "选型理由清晰（性能/一致性/成本）", "能主动讲权衡与备选方案"],
                ["这个方案在高并发下会先遇到什么瓶颈？", "如何保证数据一致性与可恢复性？"],
            ),
            _q(
                "q5", "coding", coding["text"], 3, "手撕代码",
                ["思路清晰（先讲后写）", "代码正确且边界处理完备", "能给出时间/空间复杂度分析"],
                ["能不能讲讲你代码里最容易被忽略的边界情况？", "如果要求空间 O(1)，怎么改？"],
                problem_id=coding["problem_id"],
            ),
            _q(
                "q6", "wrap", "面试快结束了，你还有什么想问我们，或者想补充的吗？",
                1, "反问与收尾",
                ["反问体现对岗位/团队的兴趣", "补充内容有信息量而非重复", "整体沟通自然得体"],
                ["你对我们这个岗位最看重什么能力？", "还有没有想展示但我们没问到的？"],
            ),
        ],
    )


def _llm_plan(llm: LLM, case: dict[str, Any]) -> QuestionPlan:
    """用 DeepSeek 生成 QuestionPlan（chat_json + pydantic 校验）；失败抛异常由调用方兜底。"""
    system = (
        "你是 AI 模拟面试官，为一场技术面试生成出题计划。输出严格 JSON（不要 markdown 代码块），schema：\n"
        '{"sections_order": [string], "questions": [{"id": string, "section": "intro|behavioral|technical|coding|wrap", '
        '"text": string, "difficulty": int(1-5), "rubric": [{"point": string, "weight": number}], '
        '"followups": [string], "target_competency": string, "problem_id": string|null}]}\n'
        "要求：6-8 题，覆盖 intro/behavioral/technical/coding/wrap；题目贴合岗位 JD 与候选人简历；"
        "rubric 每题 2-3 条可考核要点；followups 1-2 条追问；手撕代码题需给出 problem_id。全部用中文。"
    )
    user = (
        f"职位：{case['company']} {case['position']}（{case.get('level')}）\n"
        f"JD：{case['jd_text']}\n"
        f"候选人简历：{case['resume_text']}\n"
        f"候选人技能：{'、'.join(case['profile'].get('resume_skills', []))}\n"
        "请生成面试出题计划："
    )
    data = llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=3000)
    return QuestionPlan.model_validate(data)  # 校验失败抛 ValidationError → 调用方回退 canned


# ---------------------------------------------------------------------------
# Context 构建
# ---------------------------------------------------------------------------
def build_context(case: dict[str, Any], *, llm: LLM | None = None, llm_plan: bool = False) -> InterviewContext:
    profile_cfg = case.get("profile", {})
    level = case.get("level", "mid")
    resume_text = case.get("resume_text", "")

    plan = _canned_plan(case)
    if llm_plan and llm is not None:
        try:
            plan = _llm_plan(llm, case)
        except Exception:  # noqa: BLE001 — LLM plan 失败回退 canned，harness 不崩
            pass

    skills = profile_cfg.get("resume_skills", [])
    must_have = case.get("must_have", [])
    # must_have 条目若命中候选人技能关键词，视为已有优势；否则为 gap
    strengths = [s for s in must_have if any(sk in s for sk in skills)]
    gaps = [s for s in must_have if s not in strengths]

    candidate = CandidateProfile(
        name=profile_cfg.get("name", "候选人"),
        headline=f"{level} · {case.get('position', '')}方向",
        summary=resume_text[:300],
        skills=skills,
        experience=[
            ExperienceItem(
                company="上家公司/在读院校",
                role="研发工程师" if level != "junior" else "在校生",
                duration="-" ,
                bullets=resume_text.split("。")[:3],
            )
        ],
        projects=[ProjectItem(name="个人项目", role="核心开发", bullets=resume_text.split("。")[3:5])],
        level=level,
        resume_hash=str(abs(hash(resume_text))),
    )
    job = JobSpec(
        position=case["position"],
        seniority=level,
        company=case["company"],
        must_have=must_have,
        nice_to_have=case.get("nice_to_have", []),
        tech_stack=case.get("tech_stack", []),
        responsibilities=case.get("responsibilities", []),
        jd_text=case.get("jd_text", ""),
    )
    company = CompanyIntel(
        summary=f"{case['company']} 的技术面试以算法/手撕代码与项目深挖著称。",
        tech_stack=case.get("tech_stack", []),
        values=["技术深度", "结果导向"],
        interview_process="简历面 → 项目深挖 → 手撕代码 → 反问",
        recent_news=[],
        culture_notes="（来自回归语料，非实时调研）",
        coding_tendency=CodingTendency(prefers_live_coding=True, high_freq_topics=["数组", "链表", "哈希表", "动态规划"], platform="coderpad"),
        missing_company_info=True,
        sources=[Source(title="regression-corpus", url="local://regression", snippet="回归语料内置公司画像")],
    )
    gap = GapAnalysis(strengths=strengths, gaps=gaps, probe_targets=gaps, missing_skills=gaps)

    return InterviewContext(
        candidate=candidate,
        job=job,
        company=company,
        gap=gap,
        plan=plan,
        cursor=0,
        answers=[],
        scorecard=empty_scorecard(),
        status="prep",
    )


# ---------------------------------------------------------------------------
# brain 装载：mock 默认；--real 时优先真实 pipeline，失败自动降级
# ---------------------------------------------------------------------------
def _load_brain(use_real_pipeline: bool) -> tuple[Any, str]:
    if use_real_pipeline:
        try:
            from agent.pipeline import run_interview_text  # type: ignore[import-not-found]
            return run_interview_text, "pipeline"
        except Exception as exc:  # noqa: BLE001
            print(f"[runner] 真实 pipeline 未就绪（{exc!r}），降级到 mock_brain")
    return _mock_run_interview_text, "mock"


# ---------------------------------------------------------------------------
# 单场运行
# ---------------------------------------------------------------------------
def run_case(
    case: dict[str, Any],
    *,
    seed: int = 42,
    max_turns: int = 8,
    use_real_pipeline: bool = False,
    use_llm_judge: bool = True,
    llm_plan: bool = False,
    profile_overrides: dict[str, Any] | None = None,
    out_dir: str = DEFAULT_OUT_DIR,
    save: bool = True,
) -> dict[str, Any]:
    """跑一场：brain × candidate self-play → judge。返回摘要 + 落盘路径。"""
    profile = dict(case.get("profile", {}))
    profile.update({k: v for k, v in (profile_overrides or {}).items() if v is not None})
    profile.setdefault("company", case["company"])
    profile.setdefault("position", case["position"])
    profile.setdefault("jd", case["jd_text"])
    profile.setdefault("resume", case["resume_text"])
    profile.setdefault("level", case.get("level", "mid"))
    profile.setdefault("seed", seed)

    llm = LLM()
    ctx = build_context(case, llm=llm, llm_plan=llm_plan)
    candidate = CandidateAgent(profile, llm=llm)
    run_interview_text, brain_name = _load_brain(use_real_pipeline)

    transcript: list[dict[str, Any]] = []

    def logging_responder(question_text: str, transcript_so_far: Any) -> str:
        transcript.append({"role": "interviewer", "text": question_text})
        answer = candidate.respond(question_text, transcript_so_far)
        transcript.append({"role": "candidate", "text": answer})
        return answer

    if brain_name == "mock":
        ctx, transcript = run_interview_text_with_log(ctx, logging_responder, max_turns=max_turns)
    else:
        ctx = run_interview_text(ctx, logging_responder, max_turns=max_turns)

    judge = Judge(llm=llm, use_llm=use_llm_judge)
    metrics = judge.judge(ctx, transcript)
    n_turns = len([t for t in transcript if t.get("role") == "candidate"])

    payload = {
        "meta": {
            "case_id": case["id"],
            "company": case["company"],
            "position": case["position"],
            "level": case.get("level"),
            "seed": seed,
            "brain": brain_name,
            "llm_model": llm.settings.llm_model,
            "max_turns": max_turns,
            "profile": {k: v for k, v in profile.items() if k != "resume" and k != "jd"},
            "run_at": datetime.utcnow().isoformat(),
        },
        "transcript": transcript,
        "scorecard": ctx.scorecard.model_dump(mode="json"),
        "metrics": metrics,
    }
    paths: dict[str, str] = {}
    if save:
        case_dir = os.path.join(out_dir, f"{case['id']}__{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}")
        os.makedirs(case_dir, exist_ok=True)
        for name, value in [
            ("transcript.json", transcript),
            ("scorecard.json", ctx.scorecard.model_dump(mode="json")),
            ("metrics.json", metrics),
            ("ctx.json", ctx.model_dump(mode="json")),
            ("meta.json", payload["meta"]),
        ]:
            path = os.path.join(case_dir, name)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(value, fh, ensure_ascii=False, indent=2)
            paths[name] = path
        payload["paths"] = paths

    return {
        "case_id": case["id"],
        "brain": brain_name,
        "turns": n_turns,
        "overall": metrics["overall"],
        "overall_score": ctx.scorecard.overall,
        "metrics": metrics,
        "paths": paths,
    }


# ---------------------------------------------------------------------------
# 多场运行 + 汇总对比
# ---------------------------------------------------------------------------
def run_all(
    cases: list[dict[str, Any]] | None = None,
    *,
    seeds: list[int] | None = None,
    max_turns: int = 8,
    use_real_pipeline: bool = False,
    use_llm_judge: bool = False,
    llm_plan: bool = False,
    profile_overrides: dict[str, Any] | None = None,
    out_dir: str = DEFAULT_OUT_DIR,
    save: bool = True,
) -> list[dict[str, Any]]:
    cases = cases if cases is not None else CASES
    seeds = seeds or [42]
    results: list[dict[str, Any]] = []
    for case in cases:
        for seed in seeds:
            results.append(
                run_case(
                    case,
                    seed=seed,
                    max_turns=max_turns,
                    use_real_pipeline=use_real_pipeline,
                    use_llm_judge=use_llm_judge,
                    llm_plan=llm_plan,
                    profile_overrides=profile_overrides,
                    out_dir=out_dir,
                    save=save,
                )
            )
    _write_summary(results, out_dir=out_dir, save=save)
    _print_table(results)
    return results


def _write_summary(results: list[dict[str, Any]], *, out_dir: str, save: bool) -> str | None:
    if not save:
        return None
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "_summary.json")
    rows = [
        {
            "case_id": r["case_id"],
            "brain": r["brain"],
            "turns": r["turns"],
            "overall_score": r["overall_score"],
            "judge_overall": r["overall"],
            "metrics": r["metrics"]["metrics"],
            "paths": r.get("paths", {}),
        }
        for r in results
    ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"generated_at": datetime.utcnow().isoformat(), "rows": rows}, fh, ensure_ascii=False, indent=2)
    return path


def _print_table(results: list[dict[str, Any]]) -> None:
    header = f"{'case_id':<34} {'brain':<8} {'turns':>5} {'overall':>7} {'cov':>5} {'drift':>5} {'adapt':>5} {'fup':>5} {'feed':>5}"
    print("\n===== 回归汇总 =====")
    print(header)
    for r in results:
        m = r["metrics"]["metrics"]
        print(
            f"{r['case_id']:<34} {r['brain']:<8} {r['turns']:>5} {r['overall_score']:>7.1f} "
            f"{m['coverage']['score']:>5.2f} {m['anti_drift']['score']:>5.2f} "
            f"{m['difficulty_adaptivity']['score']:>5.2f} {m['followup_depth']['score']:>5.2f} "
            f"{m['feedback_actionability']['score']:>5.2f}"
        )
    print("（cov=覆盖度 drift=防飘 adapt=难度自适应 fup=追问深度 feed=反馈可执行；judge overall 见各场 metrics）")
