"""Text-mode interviewer pipeline: run the interview (live) against a
candidate_responder, then score it (post) and produce the report incl.
interviewer_os (missing_slots -> what_i_want_to_hear). No LiveKit/voice here —
this is the pure-text brain the self-play harness drives, and it's the same core
the voice shell wraps later."""

from __future__ import annotations

from typing import Callable

from .contracts import (
    AnswerRecord,
    InterviewContext,
    InterviewerOS,
    MissingSlot,
    Scorecard,
    ScoreItem,
)
from .llm import LLM


def current_question(ctx: InterviewContext):
    if ctx.cursor < len(ctx.plan.questions):
        return ctx.plan.questions[ctx.cursor]
    return None


def ask_current(ctx: InterviewContext) -> str | None:
    """Return the current question text (or None when the plan is exhausted)."""
    q = current_question(ctx)
    return q.text if q else None


def record_answer(ctx: InterviewContext, answer_text: str) -> str | None:
    """Record the candidate's answer for the current question, advance the
    cursor, and return the next question text (or None when done). Used by the
    HTTP turn API; the batch self-play loop calls something richer below."""
    q = current_question(ctx)
    if q is None:
        return None
    ctx.answers.append(AnswerRecord(question_id=q.id, transcript=answer_text or "(no answer)", status="answered"))
    ctx.cursor += 1
    return ask_current(ctx)


def transcript_so_far(ctx: InterviewContext) -> str:
    lines = []
    for a in ctx.answers:
        q = next((q for q in ctx.plan.questions if q.id == a.question_id), None)
        if q:
            lines.append(f"Q: {q.text}")
        lines.append(f"A: {a.transcript}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# live
# ---------------------------------------------------------------------------
def _suggest_difficulty(ctx: InterviewContext) -> str:
    """Light deterministic heuristic (no extra LLM). Returns harder|easier|advance|wrap."""
    if not ctx.answers:
        return "advance"
    last = ctx.answers[-1].transcript
    n = len(last.split())
    if n < 25:
        return "advance"  # candidate was concise/short
    if n > 90:
        return "wrap"    # verbose -> move on
    return "harder"


def _run_live(ctx: InterviewContext, candidate_responder: Callable[[str, str], str], max_turns: int) -> None:
    ctx.status = "live"
    turns = 0
    seen: set[str] = set()
    while ctx.cursor < len(ctx.plan.questions) and turns < max_turns:
        q = ctx.plan.questions[ctx.cursor]
        if q.id in seen:
            break
        seen.add(q.id)
        # ask the current question
        ans = candidate_responder(q.text, transcript_so_far(ctx))
        ctx.answers.append(AnswerRecord(question_id=q.id, transcript=ans or "(no answer)", status="answered"))
        # optional single follow-up: only if the question flagged followups and turns budget remains
        if q.followups and turns + 1 < max_turns:
            fu = q.followups[0]
            fu_ans = candidate_responder(fu, transcript_so_far(ctx))
            ctx.answers.append(AnswerRecord(question_id=f"{q.id}::fu", transcript=f"[follow-up] {fu_ans or ''}", status="answered"))
        ctx.cursor += 1
        turns += 1
    ctx.status = "post"


# ---------------------------------------------------------------------------
# post: scoring + interviewer_os
# ---------------------------------------------------------------------------
def _score_answer(llm: LLM, ctx: InterviewContext, a: AnswerRecord) -> ScoreItem:
    q = next((q for q in ctx.plan.questions if q.id == a.question_id), None)
    if not q:
        return ScoreItem(competency="general", score=3, evidence="", level="meets")
    rubric = " | ".join(f"{r.point}(w{r.weight:.2f})" for r in q.rubric)
    try:
        j = llm.chat_json([
            {"role": "system", "content": "You are a strict technical interviewer grader. Return ONLY JSON."},
            {"role": "user", "content":
                f"Question: {q.text}\nRubric: {rubric}\nCandidate answer: {a.transcript}\n"
                f'Score 0-5, evidence (short quote of the candidate), level in [below,meets,exceeds]. '
                f'JSON: {{"competency":"{q.target_competency}","score":3,"evidence":"...","level":"meets"}}'}],
        )
        score = float(j.get("score", 3))
        return ScoreItem(competency=str(j.get("competency", q.target_competency)),
                         score=max(0.0, min(5.0, score)),
                         evidence=str(j.get("evidence", ""))[:300],
                         level=str(j.get("level", "meets")) if j.get("level") in ("below", "meets", "exceeds") else "meets")
    except Exception:
        return ScoreItem(competency=q.target_competency, score=3.0, evidence="(grading failed)", level="meets")


def _interviewer_os(llm: LLM, ctx: InterviewContext, items: list[ScoreItem]) -> InterviewerOS:
    try:
        plan_brief = "; ".join(f"{i}. {q.target_competency}[score {next((s.score for s in items if s.competency == q.target_competency), 0)}]" for i, q in enumerate(ctx.plan.questions))
        j = llm.chat_json([
            {"role": "system", "content":
                "You are a senior interviewer writing a post-interview review. Think about what the candidate "
                "MISSED and what a strong answer should have contained. Return ONLY JSON matching "
                '{hidden_concern,why_this_question[],risk_level(low|medium|high),missing_slots['
                '{slot,evidence,why_it_matters,what_i_want_to_hear[],one_line_advice}]}.'},
            {"role": "user", "content": f"Plan: {plan_brief}\nTranscript:\n{transcript_so_far(ctx)[:6000]}"}],
        )
        slots = []
        for ms in j.get("missing_slots", [])[:8]:
            slots.append(MissingSlot(slot=str(ms.get("slot", "")), evidence=str(ms.get("evidence", ""))[:200],
                                     why_it_matters=str(ms.get("why_it_matters", "")),
                                     what_i_want_to_hear=[str(x) for x in ms.get("what_i_want_to_hear", [])][:4],
                                     one_line_advice=str(ms.get("one_line_advice", ""))[:200]))
        return InterviewerOS(hidden_concern=str(j.get("hidden_concern", "")),
                             why_this_question=[str(x) for x in j.get("why_this_question", [])][:6],
                             missing_slots=slots,
                             risk_level=str(j.get("risk_level", "low")) if j.get("risk_level") in ("low", "medium", "high") else "low")
    except Exception:
        return InterviewerOS(hidden_concern="", why_this_question=[], missing_slots=[], risk_level="low")


def _make_scorecard(llm: LLM, ctx: InterviewContext) -> Scorecard:
    planned_ids = {q.id for q in ctx.plan.questions}
    # score only real (non-follow-up) answers
    recs = [a for a in ctx.answers if a.question_id in planned_ids]
    items = [_score_answer(llm, ctx, a) for a in recs]
    overall = round((sum(i.score for i in items) / len(items) * 20) if items else 0, 1)
    try:
        worst = sorted(items, key=lambda i: i.score)[:3]
        strengths = sorted(items, key=lambda i: -i.score)[:3]
        summary = (f"整体 {overall}/100。强项：{['%s(%.1f)' % (s.competency, s.score) for s in strengths]}；"
                   f"短板：{['%s(%.1f)' % (s.competency, s.score) for s in worst]}。")
        next_steps = [f"针对 {s.competency} 做专项练习" for s in worst]
    except Exception:
        summary, next_steps = "", []
    os = _interviewer_os(llm, ctx, items)
    return Scorecard(overall=overall, items=items, summary=summary, next_steps=next_steps,
                     model_answers=[], interviewer_os=os)


def run_interview_text(ctx: InterviewContext, candidate_responder: Callable[[str, str], str], *,
                       max_turns: int = 8, llm: LLM | None = None) -> InterviewContext:
    llm = llm or LLM()
    _run_live(ctx, candidate_responder, max_turns)
    ctx.scorecard = _make_scorecard(llm, ctx)
    ctx.status = "complete"
    return ctx


def finalize(ctx: InterviewContext, llm: LLM | None = None) -> Scorecard:
    """Score whatever answers are present and return the report. Used by the HTTP turn API."""
    llm = llm or LLM()
    ctx.scorecard = _make_scorecard(llm, ctx)
    ctx.status = "complete"
    return ctx.scorecard
