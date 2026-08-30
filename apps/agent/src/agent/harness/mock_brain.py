"""mock_brain — 简化版面试官 brain（双 agent 互聊 harness 的默认驱动）。

实现与真实 pipeline 约定的**同一接口**：

    def run_interview_text(ctx, candidate_responder, *, max_turns=8) -> InterviewContext

- 按 plan 逐个问 canned 题（含按需追问 followup），调用 `candidate_responder`
  拿回答，记录进 ctx.answers（save_answer 语义），推进 cursor，到 max_turns 或
  plan 走完停止，最后生成 scorecard（规则打分 + InterviewerOS missing_slots）。
- 纯确定性、无 LLM 依赖，harness 验收可独立跑通。
- 真实 `agent.pipeline.run_interview_text` 就绪后，runner 传 `--real` 即可无缝
  切换到真 brain（接口签名一致）。

借用学长 ProjectProbe 的纪律常量：SLOT_COVERAGE_THRESHOLD / VAGUE_SCORE_THRESHOLD
（这里换算到 0-5 分制），以及 InterviewerOS.missing_slots → what_i_want_to_hear。

Transcript 契约（每轮两条）：
    {"role": "interviewer", "text": ..., "question_id": ..., "section": ...,
     "difficulty": int, "is_followup": bool, "signal": "harder"|"easier"|None}
    {"role": "candidate", "text": ..., "question_id": ..., "answer_words": int}
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from agent.contracts import (
    AnswerRecord,
    InterviewContext,
    InterviewerOS,
    MissingSlot,
    PlannedQuestion,
    Scorecard,
    ScoreItem,
)

# ---- 借鉴 Fomalhaut 的纪律常量（0-5 分制换算） ----
SLOT_COVERAGE_THRESHOLD = 0.8  # 槽位覆盖率达标线（打分 >=3 视为该槽位被覆盖）
VAGUE_SCORE_THRESHOLD = 2.5  # 低于此分视为含糊回答（0-5 分制，对应学长的 40/100）
# 字数阈值按"中文友好计数"（CJK 按字计、英文按词计），见 _word_count
THIN_WORDS = 25  # 回答字数低于此视为过于单薄 → 降难度追问
RICH_WORDS = 120  # 回答字数高于此视为内容充分 → 加难度追问
MAX_DIFFICULTY = 5

_VAGUE_MARKERS = [
    "不太确定", "不太清楚", "记不太清", "记不清", "说不清", "不是很清楚",
    "可能吧", "应该吧", "大概", "差不多", "忘了", "可能得查", "不确定",
    "按部就班", "比较常规", "没什么好说",
]

CandidateResponder = Callable[[str, list[dict[str, Any]]], str]


# ---------------------------------------------------------------------------
# 规则打分
# ---------------------------------------------------------------------------
def _word_count(text: str) -> int:
    """中文友好字数：CJK 字符按字计，ASCII 单词按词计。"""
    import re

    cjk = len(re.findall(r"[\u4e00-\u9fff]", text or ""))
    ascii_words = len(re.findall(r"[A-Za-z0-9]+", text or ""))
    return cjk + ascii_words


def _rubric_terms(point: str) -> list[str]:
    """把 rubric point 切成可用于关键词命中的词条（中文按常见分隔符切分）。"""
    import re

    tokens = re.split(r"[，。、；：:：\s()（）\-—/]+", point)
    return [t for t in tokens if len(t) >= 2]


def _main_answer_text(text: str) -> str:
    """回答记录里主答案部分（追问答案以 [面试官追问] 分隔）。"""
    marker = "[面试官追问]"
    if marker in text:
        return text.split(marker, 1)[0].strip()
    return text


def score_answer(question: PlannedQuestion, text: str) -> float:
    """0-5 规则分：字数基础分 + rubric 关键词命中加分 - 含糊措辞扣分。

    只对主答案计分（追问答案会稀释长度信号）；含糊措辞命中 ≥2 个不同标记时
    封顶 2.8，保证 weak/vague 候选人与 strong 候选人得分拉开差距。
    """
    text = _main_answer_text(text)
    words = _word_count(text)
    s = 1.0
    if words >= RICH_WORDS:
        s = 4.5
    elif words >= 70:
        s = 3.5
    elif words >= 35:
        s = 2.5
    elif words >= 20:
        s = 1.8
    markers_hit = [m for m in _VAGUE_MARKERS if m in text]
    s -= 0.5 * min(len(markers_hit), 3)
    if len(markers_hit) >= 2:
        s = min(s, 2.8)
    hits = 0
    for rubric in question.rubric:
        if any(term in text for term in _rubric_terms(rubric.point)):
            hits += 1
    s += 0.5 * hits
    return round(min(5.0, max(1.0, s)), 1)


def level_for_score(score: float) -> str:
    if score >= 4.0:
        return "exceeds"
    if score >= 3.0:
        return "meets"
    return "below"


def _first_weak_index(by_competency: list[ScoreItem]) -> int | None:
    for i, item in enumerate(by_competency):
        if item.score < 3.0:
            return i
    return None


def _build_scorecard(
    ctx: InterviewContext,
    answers_by_qid: dict[str, AnswerRecord],
) -> Scorecard:
    """确定性规则记分卡：逐题打分 → ScoreItem → interviewer_os.missing_slots。"""
    items: list[ScoreItem] = []
    for q in ctx.plan.questions:
        rec = answers_by_qid.get(q.id)
        if rec is None or not (rec.transcript or "").strip():
            continue
        score = score_answer(q, rec.transcript)
        items.append(
            ScoreItem(
                competency=q.target_competency,
                score=score,
                evidence=_main_answer_text(rec.transcript or "")[:120],
                level=level_for_score(score),
            )
        )
    avg = sum(i.score for i in items) / len(items) if items else 0.0
    overall = round(100.0 * avg / 5.0, 1)

    missing_slots: list[MissingSlot] = []
    for item in items:
        if item.score >= 3.0:
            continue  # 达到达标线 = 槽位被覆盖
        q = next((qq for qq in ctx.plan.questions if qq.target_competency == item.competency), None)
        what = [r.point for r in q.rubric] if q else [f"给出与 {item.competency} 相关的具体细节"]
        missing_slots.append(
            MissingSlot(
                slot=item.competency,
                evidence=item.evidence or "（无有效回答）",
                why_it_matters=f"「{item.competency}」是岗位关键考察点，当前回答未达到覆盖阈值（{SLOT_COVERAGE_THRESHOLD:.0%}）。",
                what_i_want_to_hear=what,
                one_line_advice=f"围绕「{item.competency}」补充结构化的具体案例与量化结果，避免空泛描述。",
            )
        )

    if any(i.score < 2.0 for i in items):
        risk = "high"
    elif any(i.score < 3.0 for i in items):
        risk = "medium"
    else:
        risk = "low"

    weak_comps = [i.competency for i in items if i.score < 3.0]
    strong_comps = [i.competency for i in items if i.score >= 4.0]
    summary = (
        f"共 {len(items)} 题，平均得分 {avg:.1f}/5（overall {overall}）。"
        + (f"强项：{'、'.join(strong_comps[:3])}。" if strong_comps else "")
        + (f"待加强：{'、'.join(weak_comps[:3])}。" if weak_comps else "各项表现均衡。")
    )
    next_steps = (
        [f"针对 {c}：补充具体案例、量化结果与技术权衡。" for c in weak_comps[:3]]
        if weak_comps
        else ["保持当前水平，重点练习开放性问题与系统设计表达。"]
    )
    idx = _first_weak_index(items)
    if idx is not None:
        weak_q = next((qq for qq in ctx.plan.questions if qq.target_competency == items[idx].competency), None)
        model_answers = [r.point for r in weak_q.rubric] if weak_q else []
    else:
        model_answers = [r.point for q in ctx.plan.questions for r in q.rubric[:1]]
    hidden_concern = (
        f"候选人在 {weak_comps[0]} 等维度存在明显短板，需在 post 报告中给出具体到 what_i_want_to_hear 的补强建议。"
        if weak_comps
        else "整体达标，重点关注深层技术细节与追问下的表现。"
    )

    return Scorecard(
        overall=overall,
        items=items,
        summary=summary,
        next_steps=next_steps,
        model_answers=model_answers,
        interviewer_os=InterviewerOS(
            hidden_concern=hidden_concern,
            why_this_question=[f"通过「{i.competency}」验证岗位核心能力。" for i in items],
            missing_slots=missing_slots,
            risk_level=risk,
        ),
    )


# ---------------------------------------------------------------------------
# 主循环（带 transcript 日志的内部实现）
# ---------------------------------------------------------------------------
def run_interview_text_with_log(
    ctx: InterviewContext,
    candidate_responder: CandidateResponder,
    *,
    max_turns: int = 8,
) -> tuple[InterviewContext, list[dict[str, Any]]]:
    """与 run_interview_text 相同，但额外返回逐轮 transcript（含元数据）。

    transcript 供 Judge / 回归语料使用；真实 brain 接入后，runner 会用
    responder 包装器自行收集等价 transcript（元数据由 Judge 归一化补齐）。
    """
    transcript: list[dict[str, Any]] = []
    ctx.status = "live"
    ctx.cursor = 0
    questions = ctx.plan.questions
    asked = 0
    total_words: list[int] = []
    ctx.answers = []

    while ctx.cursor < len(questions) and asked < max_turns:
        q = questions[ctx.cursor]
        # --- 问主问题 ---
        transcript.append(
            {
                "role": "interviewer",
                "text": q.text,
                "question_id": q.id,
                "section": q.section,
                "difficulty": q.difficulty,
                "is_followup": False,
                "signal": None,
            }
        )
        answer = (candidate_responder(q.text, transcript) or "").strip()
        transcript.append(
            {
                "role": "candidate",
                "text": answer,
                "question_id": q.id,
                "answer_words": _word_count(answer),
            }
        )
        # --- 简单难度自适应：内容充分→更难追问；单薄→更基础追问；中等→中性深挖 ---
        main_words = _word_count(answer)
        avg_words = sum(total_words) / len(total_words) if total_words else main_words
        followup_text: str | None = None
        signal: str | None = None
        if q.followups:
            if avg_words > RICH_WORDS and q.difficulty < MAX_DIFFICULTY:
                followup_text, signal = q.followups[-1], "harder"
            elif avg_words < THIN_WORDS:
                followup_text, signal = q.followups[0], "easier"
            else:
                followup_text, signal = q.followups[0], None  # 中性深挖追问
        if followup_text:
            if signal == "harder":
                fu_difficulty = min(MAX_DIFFICULTY, q.difficulty + 1)
            elif signal == "easier":
                fu_difficulty = max(1, q.difficulty - 1)
            else:
                fu_difficulty = q.difficulty
            transcript.append(
                {
                    "role": "interviewer",
                    "text": followup_text,
                    "question_id": q.id,
                    "section": q.section,
                    "difficulty": fu_difficulty,
                    "is_followup": True,
                    "signal": signal,
                }
            )
            followup_answer = (candidate_responder(followup_text, transcript) or "").strip()
            transcript.append(
                {
                    "role": "candidate",
                    "text": followup_answer,
                    "question_id": q.id,
                    "answer_words": _word_count(followup_answer),
                }
            )
            answer = f"{answer}\n\n[面试官追问] {followup_text}\n{followup_answer}"
        total_words.append(main_words)

        now = datetime.utcnow()
        ctx.answers.append(
            AnswerRecord(
                question_id=q.id,
                transcript=answer,
                score=score_answer(q, answer),
                status="answered",
                started_at=now,
                ended_at=now,
            )
        )
        ctx.cursor += 1
        asked += 1

    ctx.scorecard = _build_scorecard(ctx, {a.question_id: a for a in ctx.answers})
    ctx.status = "complete"
    return ctx, transcript


def run_interview_text(
    ctx: InterviewContext,
    candidate_responder: CandidateResponder,
    *,
    max_turns: int = 8,
) -> InterviewContext:
    """契约接口：与真实 `agent.pipeline.run_interview_text` 签名一致。

    返回更新后的 InterviewContext（含 answers / scorecard / cursor / status）。
    """
    ctx, _transcript = run_interview_text_with_log(ctx, candidate_responder, max_turns=max_turns)
    return ctx
