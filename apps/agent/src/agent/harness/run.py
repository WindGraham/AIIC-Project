"""python -m harness.run — 跑 1 场 mock-brain self-play（真实走 DeepSeek）。

打印 transcript / scorecard / judge metrics。

用法示例：
    cd apps/agent && .venv/bin/python -m harness.run
    .venv/bin/python -m harness.run --case case002-meituan-backend-engineer --style vague --strength weak
    .venv/bin/python -m harness.run --real --llm-plan        # 真实 pipeline（未就绪则自动降级）
"""

from __future__ import annotations

import argparse
import json
import sys

from .runner import DEFAULT_OUT_DIR, run_case
from .regression.cases import CASE_INDEX, CASES


def _pick_case(case_id: str | None):
    if case_id is None:
        return CASES[0]
    if case_id in CASE_INDEX:
        return CASE_INDEX[case_id]
    raise SystemExit(f"未知 case id: {case_id}。可选: {', '.join(CASE_INDEX)}")


def _print_transcript(transcript: list[dict]) -> None:
    print("\n===== TRANSCRIPT =====")
    for e in transcript:
        role = e.get("role")
        text = (e.get("text") or "").strip()
        if role == "interviewer":
            tag = "❓ 面试官"
            if e.get("is_followup"):
                tag += f"[追问/{e.get('signal')}]"
            tag += f"  (q={e.get('question_id')}, diff={e.get('difficulty')})"
        else:
            tag = "🧑‍💻 候选人"
        print(f"{tag}: {text}")


def _print_scorecard(ctx) -> None:
    sc = ctx.scorecard
    print("\n===== SCORECARD =====")
    print(f"overall: {sc.overall}  risk: {sc.interviewer_os.risk_level}  status: {ctx.status}")
    for item in sc.items:
        print(f"  [{item.level:<7}] {item.competency}: {item.score}/5  evidence: {(item.evidence or '')[:60]}...")
    os = sc.interviewer_os
    print(f"hidden_concern: {os.hidden_concern}")
    for slot in os.missing_slots:
        print(f"  MISSING {slot.slot}: want_to_hear={slot.what_i_want_to_hear} advice={slot.one_line_advice}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI 面试官 harness：跑 1 场 mock-brain self-play")
    parser.add_argument("--case", default=None, help="case id（默认第一个）")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--real", action="store_true", help="优先用真实 pipeline（未就绪自动降级 mock）")
    parser.add_argument("--llm-plan", action="store_true", help="用 DeepSeek 生成出题计划（失败回退 canned）")
    parser.add_argument("--no-llm-judge", action="store_true", help="Judge 只用规则，不调 LLM")
    parser.add_argument("--style", choices=["concise", "verbose", "vague"], default=None, help="覆盖候选人风格")
    parser.add_argument("--strength", choices=["strong", "mid", "weak"], default=None, help="覆盖候选人水平")
    parser.add_argument("--off-topic", type=float, default=None, help="覆盖跑题概率 0-1")
    parser.add_argument("--out", default=None, help="输出目录（默认 harness/run_out）")
    args = parser.parse_args(argv)

    case = _pick_case(args.case)
    overrides = {
        "style": args.style,
        "strength": args.strength,
        "off_topic_prob": args.off_topic,
    }
    result = run_case(
        case,
        seed=args.seed,
        max_turns=args.max_turns,
        use_real_pipeline=args.real,
        use_llm_judge=not args.no_llm_judge,
        llm_plan=args.llm_plan,
        profile_overrides=overrides,
        out_dir=args.out or DEFAULT_OUT_DIR,
    )

    # 重读落盘 payload 打印（与保存内容一致）
    out_dir = args.out or DEFAULT_OUT_DIR
    path = next(iter(result["paths"].values()))
    case_dir = path.rsplit("/", 1)[0]
    with open(f"{case_dir}/ctx.json", encoding="utf-8") as fh:
        ctx_data = json.load(fh)
    from agent.contracts import InterviewContext

    ctx = InterviewContext.model_validate(ctx_data)
    with open(f"{case_dir}/transcript.json", encoding="utf-8") as fh:
        transcript = json.load(fh)
    with open(f"{case_dir}/metrics.json", encoding="utf-8") as fh:
        metrics = json.load(fh)

    _print_transcript(transcript)
    _print_scorecard(ctx)
    print("\n===== JUDGE METRICS =====")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print(f"\n[ok] 落盘目录: {case_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
