"""双 agent 互聊测试 harness（文本性能测试核心）。

候选人 agent（CandidateAgent，DeepSeek 扮演求职者）↔ 面试官 brain
（默认 mock_brain，接口与真实 `agent.pipeline.run_interview_text` 一致；
真实 brain 就绪后 runner 传 --real 无缝切换）互聊，产出：
transcript + scorecard + judge metrics，落到 harness/run_out/ 供回归对比。

用法：
    cd apps/agent && .venv/bin/python -m harness.run            # 1 场 self-play
    .venv/bin/python -m harness.test_harness                    # 验收测试
"""

from .candidate import CandidateAgent
from .judge import Judge
from .mock_brain import (
    run_interview_text,
    run_interview_text_with_log,
    score_answer,
    level_for_score,
)
from .regression.cases import CASES, CASE_INDEX
from .runner import build_context, run_all, run_case

__version__ = "0.1.0"

__all__ = [
    "CandidateAgent",
    "Judge",
    "run_interview_text",
    "run_interview_text_with_log",
    "score_answer",
    "level_for_score",
    "build_context",
    "run_case",
    "run_all",
    "CASES",
    "CASE_INDEX",
    "__version__",
]
