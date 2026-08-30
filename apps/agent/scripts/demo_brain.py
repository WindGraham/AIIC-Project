"""Run a quick brain smoke test (real DeepSeek). Usage:
    cd apps/agent && .venv/bin/python -m scripts.demo_brain
You may pass a config via the .env in apps/agent/."""

import sys
from pathlib import Path

# make src/ the import root regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent.prep import build_plan
from agent.pipeline import run_interview_text
from agent.llm import LLM

SAMPLE_RESUME = ("张三，3 年经验，后端开发。精通 Python/Go，参与过电商订单系统与分布式缓存；熟悉 Redis、MySQL、Kafka。")
SAMPLE_JD = "负责订单系统后端开发，要求 Python/Go，熟悉 MySQL、Redis，了解分布式与高并发。"


def main() -> None:
    llm = LLM()

    def candidate(question: str, transcript: str) -> str:
        p = ("You are a mid-level backend engineer job candidate. Answer this interview question briefly and "
             "realistically (2-3 sentences). Use Chinese with technical English terms. Stay on topic.\n"
             f"Question: {question}\n\nAnswer:")
        return llm.chat([{"role": "user", "content": p}], max_tokens=180).strip()

    ctx = build_plan(SAMPLE_RESUME, SAMPLE_JD, "字节跳动", "后端开发工程师", "senior", "zh")
    print("PLAN sections:", ctx.plan.sections_order, "| questions:", len(ctx.plan.questions))
    for q in ctx.plan.questions:
        print("  -", q.section, f"[d{q.difficulty}]", q.text[:70])

    ctx = run_interview_text(ctx, candidate, max_turns=6)
    print("\n==== SCORECARD ====")
    print("overall:", ctx.scorecard.overall)
    for s in ctx.scorecard.items:
        print("   ", s.competency, s.score, s.level)
    os_ = ctx.scorecard.interviewer_os
    print("\n==== interviewer_os ====")
    print("  hidden_concern:", os_.hidden_concern[:160])
    for m in os_.missing_slots:
        print("  slot:", m.slot, "| advice:", m.one_line_advice[:90])
        print("      what_i_want_to_hear:", m.what_i_want_to_hear[:3])
    print("\nOK")


if __name__ == "__main__":
    main()
