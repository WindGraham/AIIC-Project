"""Judge — 用「规则 + LLM」量化一场互聊面试的质量。

规则负责**可复现的客观指标**（覆盖度 / 防飘 / 难度自适应 / 追问深度 /
反馈可执行），LLM（可选）负责给同一场面试补充定性报告（summary /
strengths / weaknesses / risks / 证据引用）。LLM 失败自动降级为纯规则，
Judge 永不崩溃。

指标口径（全部 0-1，越高越好）：
- coverage            plan 各题是否都被问到/答到（问 + 答 各占一半）
- anti_drift          是否照计划走、是否跳过手撕代码/关键考察点、有无游离题
- difficulty_adaptivity  相邻两问之间，难度是否随表现（回答字数/信号）变化
- followup_depth      是否追问、追问链最深几层
- feedback_actionability  scorecard.interviewer_os.missing_slots 是否具体到
  what_i_want_to_hear / evidence / one_line_advice
- overall             加权汇总（feedback 与 anti_drift 权重最高，防"飘"
  与"反馈可执行"正是产品差异化点）
"""

from __future__ import annotations

import json
from typing import Any

from agent.contracts import InterviewContext
from agent.llm import LLM

from .mock_brain import RICH_WORDS, THIN_WORDS, _word_count

_WEIGHTS = {
    "coverage": 0.20,
    "anti_drift": 0.25,
    "difficulty_adaptivity": 0.15,
    "followup_depth": 0.15,
    "feedback_actionability": 0.25,
}

# 收尾/寒暄类短句（不匹配 plan 也不算"游离题"）
_SHORT_PLEASANTRIES_MAX = 30  # 短于该字数的 interviewer 文本不算游离题


# ---------------------------------------------------------------------------
# transcript 归一化：wrapper 收集的 transcript 可能缺 question_id/difficulty，
# 用 plan 的题目文本/followups 反查补齐，使 mock 与真实 brain 走同一套评估。
# ---------------------------------------------------------------------------
def _normalize_transcript(transcript: list[dict[str, Any]], ctx: InterviewContext) -> list[dict[str, Any]]:
    by_text = {q.text: q for q in ctx.plan.questions}
    followup_texts = {}
    for q in ctx.plan.questions:
        for f in q.followups:
            followup_texts[f] = q

    out: list[dict[str, Any]] = []
    last_qid: str | None = None
    for e in transcript:
        role = e.get("role")
        text = (e.get("text") or "").strip()
        if role not in ("interviewer", "candidate") or not text:
            continue
        row = dict(e)
        if role == "interviewer":
            q = by_text.get(text)
            if q is not None:
                row["question_id"], row["section"], row["difficulty"], row["is_followup"] = q.id, q.section, q.difficulty, False
            elif text in followup_texts:
                q = followup_texts[text]
                row["question_id"], row["section"], row["difficulty"], row["is_followup"] = q.id, q.section, q.difficulty, True
            else:
                row["question_id"], row["section"], row["is_followup"] = None, None, False
            last_qid = row.get("question_id") or last_qid
        else:  # candidate：question_id 缺失时继承上一个 interviewer 问题
            if not row.get("question_id"):
                row["question_id"] = last_qid
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 各指标（纯规则，确定性）
# ---------------------------------------------------------------------------
def _coverage(transcript: list[dict[str, Any]], ctx: InterviewContext) -> dict[str, Any]:
    planned = {q.id for q in ctx.plan.questions}
    asked: set[str] = set()
    answered: set[str] = set()
    for e in transcript:
        qid = e.get("question_id")
        if not qid:
            continue
        if e.get("role") == "interviewer":
            asked.add(qid)
        elif e.get("role") == "candidate" and _word_count(e.get("text", "")) > 0:
            answered.add(qid)
    n = len(planned)
    asked_ratio = len(asked) / n if n else 1.0
    answered_ratio = len(answered) / n if n else 1.0
    score = round(0.5 * asked_ratio + 0.5 * answered_ratio, 3)
    return {
        "score": score,
        "questions_planned": n,
        "questions_asked": len(asked),
        "questions_answered": len(answered),
        "unasked": sorted(planned - asked),
        "unanswered": sorted(planned - answered),
    }


def _anti_drift(transcript: list[dict[str, Any]], ctx: InterviewContext) -> dict[str, Any]:
    interviewer_entries = [e for e in transcript if e.get("role") == "interviewer"]
    off_plan: list[str] = []
    for e in interviewer_entries:
        text = (e.get("text") or "").strip()
        if e.get("question_id") or e.get("is_followup"):
            continue
        if len(text) <= _SHORT_PLEASANTRIES_MAX:
            continue  # 寒暄/收尾不算游离
        off_plan.append(text)
    on_plan_ratio = round(1.0 - len(off_plan) / max(1, len(interviewer_entries)), 3)

    critical = [q for q in ctx.plan.questions if q.section == "coding" or q.problem_id or "手撕" in q.text]
    asked_ids = {e.get("question_id") for e in interviewer_entries}
    skipped_critical = [q.id for q in critical if q.id not in asked_ids]
    if critical:
        critical_kept = round(1.0 - len(skipped_critical) / len(critical), 3)
    else:
        critical_kept = 1.0
    score = round(0.6 * on_plan_ratio + 0.4 * critical_kept, 3)
    return {
        "score": score,
        "on_plan_ratio": on_plan_ratio,
        "off_plan_questions": off_plan,
        "critical_questions": [q.id for q in critical],
        "skipped_critical": skipped_critical,
    }


def _difficulty_adaptivity(transcript: list[dict[str, Any]]) -> dict[str, Any]:
    # 把「主问题 + 其追问」视为一个 block；block 之间才构成难度转移
    blocks: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for e in transcript:
        if e.get("role") == "interviewer":
            diff = e.get("difficulty")
            if diff is None:
                continue
            if e.get("is_followup"):
                if cur is not None:
                    cur["signals"].append(e.get("signal"))
            else:
                cur = {"difficulty": diff, "signals": [], "answer_words": None}
                blocks.append(cur)
        elif e.get("role") == "candidate" and cur is not None and cur["answer_words"] is None:
            cur["answer_words"] = e.get("answer_words") or _word_count(e.get("text", ""))
    transitions: list[dict[str, Any]] = []
    prev = None
    for b in blocks:
        if prev is not None:
            adaptive = bool(prev["signals"])  # 上一题出现过 harder/easier 追问信号
            if not adaptive and prev["answer_words"] is not None:
                w = prev["answer_words"]
                if w > RICH_WORDS and b["difficulty"] > prev["difficulty"]:
                    adaptive = True
                elif w < THIN_WORDS and b["difficulty"] < prev["difficulty"]:
                    adaptive = True
            transitions.append(
                {
                    "from": prev["difficulty"],
                    "to": b["difficulty"],
                    "prev_answer_words": prev["answer_words"],
                    "signals": prev["signals"],
                    "adaptive": adaptive,
                }
            )
        prev = b
    n = len(transitions)
    score = round(sum(1 for t in transitions if t["adaptive"]) / n, 3) if n else 1.0
    return {"score": score, "adaptive_transitions": sum(1 for t in transitions if t["adaptive"]), "total_transitions": n, "transitions": transitions}


def _followup_depth(transcript: list[dict[str, Any]], ctx: InterviewContext) -> dict[str, Any]:
    interviewer = [e for e in transcript if e.get("role") == "interviewer"]
    followup_entries = [e for e in interviewer if e.get("is_followup")]
    # 追问链深度：连续 followup 条目的最大 run 长度
    max_depth = 0
    run = 0
    for e in interviewer:
        if e.get("is_followup"):
            run += 1
            max_depth = max(max_depth, run)
        else:
            run = 0
    n = len(ctx.plan.questions)
    ratio = len(followup_entries) / n if n else 0.0
    score = round(min(1.0, 0.4 * min(1.0, ratio) + 0.6 * min(1.0, max_depth / 2)), 3)
    return {
        "score": score,
        "followup_count": len(followup_entries),
        "max_depth": max_depth,
        "followup_questions": [(e.get("text") or "")[:60] for e in followup_entries],
    }


def _feedback_actionability(ctx: InterviewContext) -> dict[str, Any]:
    slots = ctx.scorecard.interviewer_os.missing_slots
    if not slots:
        return {
            "score": 1.0,
            "missing_slots": 0,
            "with_what_i_want_to_hear": 0,
            "with_advice": 0,
            "with_evidence": 0,
            "note": "无 missing_slots（候选人无明显短板，或未打分）",
        }
    n = len(slots)
    with_what = sum(1 for s in slots if len([w for w in s.what_i_want_to_hear if (w or "").strip()]) >= 2)
    with_evidence = sum(1 for s in slots if (s.evidence or "").strip())
    with_advice = sum(1 for s in slots if (s.one_line_advice or "").strip())
    score = round(0.5 * with_what / n + 0.3 * with_evidence / n + 0.2 * with_advice / n, 3)
    return {
        "score": score,
        "missing_slots": n,
        "with_what_i_want_to_hear": with_what,
        "with_evidence": with_evidence,
        "with_advice": with_advice,
    }


# ---------------------------------------------------------------------------
# LLM 定性补充（可选；失败自动降级）
# ---------------------------------------------------------------------------
def _llm_report(llm: LLM, ctx: InterviewContext, transcript: list[dict[str, Any]]) -> dict[str, Any]:
    turns_txt = "\n".join(
        f"{'面试官' if e['role'] == 'interviewer' else '候选人'}：{(e.get('text') or '')[:500]}"
        for e in transcript[-20:]
    )
    scorecard_txt = ctx.scorecard.model_dump_json()
    system = (
        "你是 AI 模拟面试平台的质量评估助手。基于面试转写与记分卡，输出严格 JSON（不要 markdown）："
        '{"summary": string, "strengths": [string], "weaknesses": [string], "risks": [string], "evidence_quotes": [string]}。'
        "summary 用一句话概括本场面试质量；strengths/weaknesses 各 1-3 条具体到能力点；"
        "risks 指出面试官可能的疏漏（如跳过手撕代码、追问不足）；evidence_quotes 摘录转写中 1-2 条关键证据（原话）。全部用中文。"
    )
    user = f"面试转写（节选）：\n{turns_txt}\n\n记分卡：\n{scorecard_txt}"
    data = llm.chat_json([{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=1500)
    return {
        "summary": str(data.get("summary", "")),
        "strengths": [str(x) for x in data.get("strengths", [])],
        "weaknesses": [str(x) for x in data.get("weaknesses", [])],
        "risks": [str(x) for x in data.get("risks", [])],
        "evidence_quotes": [str(x) for x in data.get("evidence_quotes", [])],
    }


class Judge:
    """量化一场面试。use_llm=True 时额外调一次 DeepSeek 生成定性报告。"""

    def __init__(self, llm: LLM | None = None, use_llm: bool = False) -> None:
        self.llm = llm or (LLM() if use_llm else None)
        self.use_llm = use_llm and self.llm is not None

    def judge(self, ctx: InterviewContext, transcript: list[dict[str, Any]]) -> dict[str, Any]:
        norm = _normalize_transcript(transcript, ctx)
        metrics = {
            "coverage": _coverage(norm, ctx),
            "anti_drift": _anti_drift(norm, ctx),
            "difficulty_adaptivity": _difficulty_adaptivity(norm),
            "followup_depth": _followup_depth(norm, ctx),
            "feedback_actionability": _feedback_actionability(ctx),
        }
        overall = round(
            sum(_WEIGHTS[k] * metrics[k]["score"] for k in _WEIGHTS), 3
        )
        rule_summary = (
            f"覆盖率 {metrics['coverage']['score']:.0%}（问 {metrics['coverage']['questions_asked']}/"
            f"{metrics['coverage']['questions_planned']} 答 {metrics['coverage']['questions_answered']}/"
            f"{metrics['coverage']['questions_planned']}），照计划 {metrics['anti_drift']['score']:.0%}，"
            f"难度自适应 {metrics['difficulty_adaptivity']['score']:.0%}，"
            f"追问深度 {metrics['followup_depth']['score']:.0%}（{metrics['followup_depth']['followup_count']} 次追问），"
            f"反馈可执行 {metrics['feedback_actionability']['score']:.0%}。"
        )
        report: dict[str, Any] = {}
        engine = "rules"
        if self.use_llm:
            try:
                report = _llm_report(self.llm, ctx, norm)
                engine = "rules+llm"
            except Exception as exc:  # noqa: BLE001
                report = {"llm_error": repr(exc)[:200]}
                engine = "rules"
        return {
            "overall": overall,
            "weights": dict(_WEIGHTS),
            "metrics": metrics,
            "summary": report.get("summary") or rule_summary,
            "report": report,
            "engine": engine,
        }


def pretty_metrics(metrics: dict[str, Any]) -> str:
    out = [f"overall: {metrics['overall']}  (engine: {metrics['engine']})"]
    for key, m in metrics["metrics"].items():
        out.append(f"  {key}: {m['score']}  {json.dumps({k: v for k, v in m.items() if k != 'score'}, ensure_ascii=False)}")
    if metrics.get("summary"):
        out.append(f"  summary: {metrics['summary']}")
    return "\n".join(out)
