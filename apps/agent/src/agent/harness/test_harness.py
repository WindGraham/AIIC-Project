"""python -m harness.test_harness — harness 验收测试（无需 pytest）。

跑 1 场 mock-brain self-play（真实走 DeepSeek，默认 rules-only judge 保证快速
与确定性），断言：
  - 产出 transcript + scorecard + judge metrics
  - 5 <= 轮数 <= max_turns；角色交替 interviewer/candidate
  - ctx.answers 全部 status=answered 且 transcript 非空
  - scorecard 通过 pydantic 校验（overall 0-100、items 非空、interviewer_os 齐全）
  - metrics 五个维度齐全且分数在 0-1
  - Judge 纯规则可复现（同转写两次判分一致）
  - mock brain 契约：cursor == 问过的题数；不跳过 plan 题目
可选 --with-llm 走一遍 LLM judge（更慢，验证 LLM 路径不崩）。
"""

from __future__ import annotations

import argparse
import sys

from .judge import Judge
from .mock_brain import run_interview_text, run_interview_text_with_log
from .regression.cases import CASES
from .runner import build_context

_PASS = 0
_FAIL = 0


def _check(cond: bool, msg: str) -> None:
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        print(f"  [PASS] {msg}")
    else:
        _FAIL += 1
        print(f"  [FAIL] {msg}")


# ---------------------------------------------------------------------------
# 纯单元断言（不依赖 LLM）
# ---------------------------------------------------------------------------
def _unit_tests() -> None:
    print("[unit] 纯规则单元断言")
    from .mock_brain import level_for_score, score_answer
    from .runner import _canned_plan

    plan = _canned_plan(CASES[0])
    _check(len(plan.questions) >= 5, f"canned plan 至少 5 题（实际 {len(plan.questions)}）")
    _check({q.section for q in plan.questions} >= {"intro", "coding", "wrap"}, "plan 覆盖 intro/coding/wrap")
    _check(any(q.problem_id for q in plan.questions), "plan 包含手撕代码题（problem_id 非空）")

    rich_q = plan.questions[0]
    _check(score_answer(rich_q, "你好" * 5 + "。".join(["具体方案与权衡"] * 30)) >= 3.0, "长回答得分 >= 3")
    _check(score_answer(rich_q, "大概吧，不太确定，记不清了") < 2.0, "含糊回答得分 < 2")
    _check(level_for_score(4.2) == "exceeds", "level_for_score(4.2)=exceeds")
    _check(level_for_score(3.0) == "meets", "level_for_score(3.0)=meets")
    _check(level_for_score(2.0) == "below", "level_for_score(2.0)=below")

    from .runner import _load_brain

    _, name = _load_brain(use_real_pipeline=False)
    _check(name == "mock", "默认 brain = mock")
    _, name2 = _load_brain(use_real_pipeline=True)
    _check(name2 in ("pipeline", "mock"), f"--real 未就绪时安全降级（实际 {name2}）")


# ---------------------------------------------------------------------------
# 端到端：1 场 mock-brain self-play（走 DeepSeek 候选人）
# ---------------------------------------------------------------------------
def _selfplay_test(max_turns: int, use_llm_judge: bool) -> None:
    print(f"[self-play] 1 场 mock-brain 互聊（max_turns={max_turns}, llm_judge={use_llm_judge}）")
    case = CASES[0]
    profile = dict(case["profile"])
    profile.update(
        company=case["company"], position=case["position"], jd=case["jd_text"],
        resume=case["resume_text"], seed=7,
    )

    ctx = build_context(case)
    _check(ctx.status == "prep" and ctx.cursor == 0, "初始 ctx: prep / cursor=0")

    from .candidate import CandidateAgent

    candidate = CandidateAgent(profile)
    transcript: list[dict] = []

    def responder(question: str, transcript_so_far) -> str:
        transcript.append({"role": "interviewer", "text": question})
        answer = candidate.respond(question, transcript_so_far)
        transcript.append({"role": "candidate", "text": answer})
        return answer

    ctx, transcript = run_interview_text_with_log(ctx, responder, max_turns=max_turns)

    cand_turns = [t for t in transcript if t.get("role") == "candidate"]
    iv_turns = [t for t in transcript if t.get("role") == "interviewer"]
    main_rounds = [t for t in iv_turns if not t.get("is_followup")]
    _check(5 <= len(main_rounds) <= max_turns, f"主问题轮数 5..{max_turns}（实际 {len(main_rounds)}）")
    _check(len(iv_turns) == len(cand_turns), "interviewer/candidate 条目数相等")
    _check(all((t.get("text") or "").strip() for t in cand_turns), "候选回答均非空")
    _check(ctx.status == "complete", f"ctx.status=complete（实际 {ctx.status}）")
    _check(ctx.cursor == len([a for a in ctx.answers if a.status == "answered"]), "cursor == answered 数")
    _check(all(a.status == "answered" and (a.transcript or "").strip() for a in ctx.answers), "answers 全部 answered 且非空")
    asked_ids = {e.get("question_id") for e in iv_turns if e.get("question_id")}
    _check(asked_ids == {a.question_id for a in ctx.answers}, "asked question ids 与 answers 一一对应")

    sc = ctx.scorecard
    _check(0 <= sc.overall <= 100, f"scorecard.overall 在 0-100（实际 {sc.overall}）")
    _check(len(sc.items) > 0, "scorecard.items 非空")
    _check(all(0 <= i.score <= 5 for i in sc.items), "每项 score 在 0-5")
    _check(sc.interviewer_os.risk_level in ("low", "medium", "high"), "interviewer_os.risk_level 合法")
    _check(isinstance(sc.interviewer_os.missing_slots, list), "interviewer_os.missing_slots 存在")
    _check(all(s.what_i_want_to_hear for s in sc.interviewer_os.missing_slots), "missing_slots 均给出 what_i_want_to_hear")

    judge = Judge(use_llm=use_llm_judge)
    metrics = judge.judge(ctx, transcript)
    for key in ("coverage", "anti_drift", "difficulty_adaptivity", "followup_depth", "feedback_actionability"):
        m = metrics["metrics"][key]
        _check(0.0 <= m["score"] <= 1.0, f"metrics.{key}.score 在 0-1（实际 {m['score']}）")
    _check(0.0 <= metrics["overall"] <= 1.0, f"judge overall 在 0-1（实际 {metrics['overall']}）")
    _check(metrics["summary"], "metrics.summary 非空")

    if not use_llm_judge:
        metrics2 = judge.judge(ctx, transcript)
        _check(metrics2 == metrics, "Judge 纯规则可复现（两次判分一致）")

    # 契约接口：run_interview_text 返回 InterviewContext（不返回 transcript）
    ctx2 = build_context(case)
    ctx2 = run_interview_text(ctx2, lambda q, t: "测试回答。" * 8, max_turns=3)
    _check(ctx2.cursor == 3 and len(ctx2.answers) == 3, "契约接口 max_turns=3 时恰好 3 轮")
    _check(ctx2.scorecard.overall > 0, "契约接口同样产出 scorecard")
    print(f"  [self-play] overall_score={ctx.scorecard.overall}  judge_overall={metrics['overall']}  engine={metrics['engine']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="harness 验收测试")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--with-llm", action="store_true", help="LLM judge 也跑一遍（慢）")
    args = parser.parse_args(argv)

    _unit_tests()
    _selfplay_test(args.max_turns, use_llm_judge=False)
    if args.with_llm:
        _selfplay_test(args.max_turns, use_llm_judge=True)

    print(f"\n===== RESULT: {_PASS} passed, {_FAIL} failed =====")
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
