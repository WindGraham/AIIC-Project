"""Live interviewer flow: a REAL, time-aware interview, not a thrown question list.

The old brain (prep plan + cursor) just walked a pre-fetched question list one by
one ("网上搜题一个个丢给候选人"). This module replaces that with a **per-round
LLM agent** that genuinely interviews the candidate:

  · it knows the interview is ~60 min: 40 min of project / personal / fundamentals
    + 20 min of hand-code (configurable), and it is told the elapsed time and the
    remaining budget so it can pace itself;
  · it opens with self-intro -> one specific project -> then progressively probes
    project details and fundamentals, choosing depth/follow-ups based on how long
    the candidate took and how much time is left;
  · EVERY round rebuilds an agent whose prompt contains: the interviewer identity
    (persona), the candidate's resume, this interview's special requirements
    (job/JD/scenario/notes), the cross-interview memory, and the FULL chat history.

The director (this class) is deterministic about WHEN to move between phases (by
elapsed time as the hard cap, with a turn-based fallback so a fast demo/test still
reaches the coding round), while the LLM decides WHAT to say and how deep to probe.

Phase order: intro -> project -> probe -> coding -> wrap (coding skipped when the
booking has no coding round). The flow appends dynamic PlannedQuestion/AnswerRecord
back into the InterviewContext so the existing report/scoring still works.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from .contracts import (
    AnswerRecord,
    InterviewContext,
    PlannedQuestion,
    QuestionPlan,
    RubricItem,
)
from .llm import LLM
from .prep import _persona_style  # reuse persona tone

logger = logging.getLogger("agent.liveflow")

# Ordered phase ladder.
_PHASES = ["intro", "project", "probe", "coding", "wrap"]

# Default budgets (minutes). Conversation (group) = intro+project+probe.
DEFAULT_GROUP_MIN = 40
DEFAULT_CODING_MIN = 20
DEFAULT_TOTAL_MIN = DEFAULT_GROUP_MIN + DEFAULT_CODING_MIN


def _persona_line(persona: str) -> str:
    """Short identity line for the prompt (distinct from prep's tone string)."""
    return {
        "peer": "你是一位与候选人平级的同事面试官，语气平等友好，重在技术切磋与引导，压力小。",
        "high-peer": "你是一位资深同级面试官，专业而平等，重视方法、复杂度与工程取舍，压力中等。",
        "manager": "你是一位主管面试官，语气正式、有压迫感，重视全局判断、owner-ship 与结果导向，压力较大。",
    }.get(persona or "high-peer", "你是一位资深技术面试官。")


def _candidate_brief(ctx: InterviewContext) -> str:
    """Compact resume for the per-round prompt (the '包含候选人的简历' requirement)."""
    c = ctx.candidate
    lines = [f"候选人：{c.name}  ({c.headline or '应届/社招'})"]
    if c.summary:
        lines.append(f"简介：{c.summary}")
    if c.skills:
        lines.append("技能：" + "、".join(c.skills))
    for i, e in enumerate(c.experience[:3]):
        lines.append(f"经历{i + 1}: {e.company} {e.role} ({e.duration}); " + "；".join(e.bullets))
    for p in c.projects[:3]:
        lines.append(f"项目: {p.name} ({p.role}); " + "；".join(p.bullets))
    return "\n".join(lines)


def _requirements_brief(ctx: InterviewContext, notes: str = "", scenario: str = "algorithm") -> str:
    """Special requirements for THIS interview (job/JD + scenario + notes)."""
    j = ctx.job
    gap = ctx.gap
    lines = [f"岗位：{j.position}（{j.seniority}）@{j.company}"]
    if j.tech_stack:
        lines.append("技术栈：" + "、".join(j.tech_stack))
    if j.must_have:
        lines.append("硬性要求：" + "、".join(j.must_have))
    if j.nice_to_have:
        lines.append("加分项：" + "、".join(j.nice_to_have))
    if gap.gaps:
        lines.append("待考察薄弱点：" + "、".join(gap.gaps))
    if gap.probe_targets:
        lines.append("重点深挖：" + "、".join(gap.probe_targets))
    if scenario and scenario != "algorithm":
        lines.append(f"场景：{scenario}")
    if notes:
        lines.append(f"补充要求：{notes}")
    return "\n".join(lines)


class LiveFlow:
    """A single live interview: deterministic phase director + per-round agent."""

    def __init__(
        self,
        ctx: InterviewContext,
        *,
        lang: str = "zh",
        has_coding: bool = True,
        notes: str = "",
        scenario: str = "algorithm",
        group_min: int = DEFAULT_GROUP_MIN,
        coding_min: int = DEFAULT_CODING_MIN,
        probe_max_turns: int = 8,
        coding_max_turns: int = 5,
    ):
        self.ctx = ctx
        self.lang = lang
        self.has_coding = has_coding
        self.notes = notes or ""
        self.scenario = scenario or "algorithm"
        self.group_min = int(group_min or DEFAULT_GROUP_MIN)
        self.coding_min = int(coding_min or DEFAULT_CODING_MIN)
        self.total_min = self.group_min + self.coding_min
        # Turn-based safety caps: in a fast demo/test the interview must still reach
        # coding + wrap (a real 40/20-min interview is bounded by time, not by these).
        self.probe_max_turns = int(probe_max_turns or 8)
        self.coding_max_turns = int(coding_max_turns or 5)

        self.turns: list[dict[str, str]] = []  # full chat history [{role, content}]
        self.started_at = time.monotonic()
        self.phase_started_at = self.started_at
        self.phase_index = 0  # index into _PHASES
        self.done = False
        self.coding_announced = False
        self.coding_elapsed_start: Optional[float] = None
        self._qseq = 0
        self._phase_entry_users = 0  # user-turn count at which we entered current phase
        self._opened = False  # the opening self-intro has been spoken once

        self.ctx.status = "live"
        self.ctx.cursor = 0

    # ---- phase helpers -----------------------------------------------------
    def _ordered_phases(self) -> list[str]:
        return [p for p in _PHASES if not (p == "coding" and not self.has_coding)]

    @property
    def phase(self) -> str:
        ordered = self._ordered_phases()
        return ordered[self.phase_index] if self.phase_index < len(ordered) else "wrap"

    def _phase_budget_min(self, phase: str) -> int:
        if phase == "coding":
            return self.coding_min
        if phase == "intro":
            return 4
        if phase == "project":
            return 5
        if phase == "wrap":
            return 2
        # probe gets the rest of the group budget
        return max(2, self.group_min - 4 - 5)

    def _elapsed_min(self) -> float:
        return (time.monotonic() - self.started_at) / 60.0

    def _group_elapsed_min(self) -> float:
        if self.coding_elapsed_start is not None:
            return (self.coding_elapsed_start - self.started_at) / 60.0
        return self._elapsed_min()

    # ---- public API --------------------------------------------------------
    def opening_line(self) -> str:
        """First interviewer utterance: request a self-intro. Idempotent."""
        if self._opened:
            return self.turns[-1]["content"]
        self._opened = True
        line = "你好，很高兴见到你。这是一场约 60 分钟的模拟面试——前 40 分钟我们聊你的项目、经历和基础，后 20 分钟做一道手撕代码题。先请你做个自我介绍吧，说说你的教育背景和最有代表性的项目或经历。"
        self.turns.append({"role": "assistant", "content": line})
        return line

    @property
    def opened(self) -> bool:
        return self._opened

    def current_phase(self) -> str:
        return self.phase

    def section_for_ui(self) -> str:
        """Map live phase to the plan's section names used by the UI/CodingPanel.

        The plan schema only allows {intro|behavioral|technical|coding|wrap}, so
        'project' maps to 'behavioral' (project/experience profiling).
        """
        m = {"intro": "intro", "project": "behavioral", "probe": "technical",
             "coding": "coding", "wrap": "wrap"}
        return m.get(self.phase, "technical")

    def coding_problem_id(self) -> Optional[str]:
        """The plan's coding problem (if a coding round exists in the plan)."""
        if not self.has_coding:
            return None
        q = next((q for q in self.ctx.plan.questions if q.section == "coding"), None)
        return q.problem_id if q else None

    def next_line(self, candidate_text: str) -> str:
        """Record the candidate's answer and produce the interviewer's next line.

        Uses `asyncio.to_thread` externally when called from the async voice WS.
        This is the per-round agent: it rebuilds a full prompt (identity + resume +
        requirements + memory + FULL history) every turn.
        """
        if self.done:
            return "面试已结束，感谢你的回答，可以查看你的报告了。"

        user_text = (candidate_text or "").strip() or "(未作答)"
        self.turns.append({"role": "user", "content": user_text})

        # Record the candidate's answer + the question it answers (for scoring).
        self._record_answer(user_text)

        # Ask the agent for the line in the CURRENT phase.
        line = self._ask_agent()
        if not line:
            line = self._fallback_line()
        self.turns.append({"role": "assistant", "content": line})

        # Advance the director AFTER speaking, so a wrap-up line is generated first.
        self._advance_phase()

        return line

    # ---- scoring feed ------------------------------------------------------
    def _record_answer(self, user_text: str) -> None:
        """Append the asked question + candidate answer into ctx so /report works."""
        try:
            prev = self.turns[-2] if len(self.turns) >= 2 else None
            question_text = (prev or {}).get("content", "") if (prev or {}).get("role") == "assistant" else ""
            self._qseq += 1
            qid = f"live-q{self._qseq}"
            self.ctx.plan.questions.append(PlannedQuestion(
                id=qid,
                section=self.section_for_ui(),
                text=(question_text or "（请描述你的相关经历）")[:400],
                difficulty=3,
                rubric=[RubricItem(point="depth", weight=1.0)],
                followups=[],
                target_competency=self.phase,
            ))
            self.ctx.answers.append(AnswerRecord(
                question_id=qid,
                transcript=user_text,
                status="answered",
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("liveflow _record_answer failed: %s", exc)

    # ---- per-round agent ---------------------------------------------------
    def _history_block(self) -> str:
        """The FULL chat history (the '全部聊天记录' requirement)."""
        if not self.turns:
            return "（尚无对话）"
        return "\n".join(f"[{'面试官' if t['role'] == 'assistant' else '候选人'}] {t['content']}" for t in self.turns)

    def _ask_agent(self) -> str:
        """Build the full per-round prompt and ask the LLM for the next line."""
        phase = self.phase
        elapsed = self._group_elapsed_min()
        remaining = max(0.0, self.group_min - elapsed)
        next_phase = self._next_phase_name()
        persona = _persona_line(getattr(self.ctx, "persona", "high-peer"))
        style = _persona_style(getattr(self.ctx, "persona", "high-peer"))
        memory = getattr(self.ctx, "memory_brief", "") or ""

        sys_ = (
            f"你是一位正在主持真实技术面试的资深面试官。{persona} 面试风格：{style}\n"
            "【面试结构】约60分钟：前40分钟聊项目/经历/基础，后20分钟手撕代码。\n"
            f"【当前阶段】{phase}（下一阶段：{next_phase}）\n"
            f"【时间预算】对话阶段已用约 {elapsed:.1f} 分钟，还剩约 {remaining:.1f} 分钟；"
            f"代码阶段{self.coding_min}分钟。\n"
            f"【候选人简历】\n{_candidate_brief(self.ctx)}\n"
            f"【本场特点】\n{_requirements_brief(self.ctx, self.notes, self.scenario)}\n"
            f"{('【跨场记忆】' + memory) if memory else ''}\n"
            "【面试规则】\n"
            "- 用中文口语化地说一句话推进面试；只问一个问题，不要一次抛多个问题、不要报题号。\n"
            "- 根据候选人上一句的长短和深度调整：答得浅就追问细节，答得深就换一个点，时间少就加快。\n"
            "- 经过自我介绍后，选一个具体项目让候选人介绍；然后在 probe 阶段深入追问该项目细节"
            "（架构/难点/取舍/指标/踩坑），再自然过渡到该岗位相关的理论/基础。\n"
            "- 不要复述问题，不要提评分或打分，不要说'我记录了'。\n"
            f"- 当前阶段是【{phase}】：{self._phase_guidance(phase, remaining)}\n"
        )
        user = (
            "【到目前为止的完整对话】\n" + self._history_block() +
            "\n\n【请输出】你作为面试官接下来的那句话。只需要输出这一句话本身，不要加引号或解释。"
        )
        try:
            llm = LLM()
            line = llm.chat(
                [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
                max_tokens=300,
                temperature=0.8,
                timeout=45.0,
            )
            line = (line or "").strip().strip('"').strip()
            return line[:500]
        except Exception as exc:  # noqa: BLE001
            logger.warning("liveflow _ask_agent failed: %s", exc)
            return ""

    def _phase_guidance(self, phase: str, remaining: float) -> str:
        if phase == "intro":
            return "请让候选人自我介绍。这是面试开场，你的一句话要自然、有亲和力。"
        if phase == "project":
            return "听完自我介绍后，请让候选人挑一个最有代表性的具体项目来介绍。"
        if phase == "probe":
            return "这是主环节：围绕候选人刚介绍的项目追问细节（架构、难点、数据、取舍、踩坑），" \
                   "再结合岗位要求问相关基础与场景。剩余时间不少时可多问几轮并逐层加深；" \
                   "剩余时间少则挑最关键的一两点快速问。"
        if phase == "coding":
            return "请引导候选人进入手撕代码环节：说明题目并要求其先在代码区作答，你来观察与提示。"
        if phase == "wrap":
            return "请做收尾：感谢候选人，简要点出亮点与可改进处，并留时间让候选人反问。(你说完这句即结束)"
        return ""

    def _next_phase_name(self) -> str:
        ordered = self._ordered_phases()
        idx = self.phase_index if self.phase_index < len(ordered) else len(ordered) - 1
        return ordered[idx + 1] if idx + 1 < len(ordered) else "wrap"

    def _advance_phase(self) -> None:
        """Deterministic phase director.

        - Hard time cap: if the whole group budget is consumed and we are not yet
          in coding/wrap, force the move so the interview is never late.
        - Turn-based caps: probe exits after ``probe_max_turns`` answers and coding
          after ``coding_max_turns`` answers (a fast demo/test still reaches the
          hand-code round + wrap without waiting a real 40/20 minutes).
        - intro -> project -> probe each advance after their first answer.
        - `done` is set only when leaving wrap, so the wrap-up line is spoken first.
        """
        ordered = self._ordered_phases()
        idx = self.phase_index if self.phase_index < len(ordered) else len(ordered) - 1
        cur = ordered[idx]

        # (0) If the interview is already wrapped up, never re-enter.
        if self.done:
            return

        # (1) Hard group time cap -> push toward coding / wrap.
        if cur in ("intro", "project", "probe") and self._group_elapsed_min() >= self.group_min:
            self._enter_phase(ordered, min(idx + 1, len(ordered) - 1))
            return

        # (2) Coding phase: advance to wrap after the coding budget (time *or* turns).
        if cur == "coding":
            time_up = (
                self.coding_elapsed_start is not None
                and (time.monotonic() - self.coding_elapsed_start) / 60.0 >= self.coding_min
            )
            turns_up = self._phase_answer_count() >= self.coding_max_turns
            if time_up or turns_up:
                self._enter_phase(ordered, min(idx + 1, len(ordered) - 1))
                if self.phase == "wrap":
                    # We just entered wrap; it will be spoken on the NEXT next_line.
                    pass
            return

        # (3) Probe: stay for a bounded number of answers (turn cap) or time cap.
        if cur == "probe":
            if self._phase_answer_count() >= self.probe_max_turns:
                self._enter_phase(ordered, min(idx + 1, len(ordered) - 1))
                if self.phase == "coding" and not self.coding_announced:
                    self.coding_announced = True
                    self.coding_elapsed_start = time.monotonic()
            return

        # (4) Short-lived phases advance after their first answer; wrapping marks done.
        budget = {"intro": 1, "project": 1, "wrap": 1}
        if cur in budget and self._phase_answer_count() >= budget[cur]:
            if cur == "wrap":
                # Spoke the farewell already -> the interview is over.
                self.done = True
                return
            self._enter_phase(ordered, min(idx + 1, len(ordered) - 1))

    def _phase_answer_count(self) -> int:
        """Number of candidate answers recorded in the CURRENT phase (since entry)."""
        return self._phase_user_count() - self._phase_entry_users

    def _enter_phase(self, ordered: list[str], new_index: int) -> None:
        if new_index == self.phase_index:
            return
        self.phase_index = new_index
        self.phase_started_at = time.monotonic()
        self._phase_entry_users = self._phase_user_count()
        # Entering coding starts the coding timer (so time cap applies).
        if self.phase == "coding" and not self.coding_announced:
            self.coding_announced = True
            self.coding_elapsed_start = time.monotonic()

    def _phase_user_count(self) -> int:
        return sum(1 for t in self.turns if t.get("role") == "user")

    def _fallback_line(self) -> str:
        by_phase = {
            "intro": "请先做个自我介绍吧。",
            "project": "可以说说你最有代表性的一个项目吗？",
            "probe": "这个项目里你遇到了哪些难点，是怎么解决的？",
            "coding": "我们进入手撕代码环节，请看一下题目并在左侧代码区作答。",
            "wrap": "感谢你的回答，可以看看你的面试报告。",
        }
        return by_phase.get(self.phase, "请继续。")


def make_flow(ctx: InterviewContext, **kw) -> LiveFlow:
    """Convenience factory (used by main when a live turn starts)."""
    return LiveFlow(ctx, **kw)
