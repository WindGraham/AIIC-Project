"""Live interviewer flow: an EXPLICIT interview STATE MACHINE, not a thrown list.

The old brain (prep plan + cursor) walked a pre-fetched question list one by one.
This is a genuine interviewer driven by a clear state machine, so every state's
agent input/output is controlled and easy to test (particularly the TEXT flow):

    intro  (介绍自己)  -> project (介绍项目) -> project_qa (提问项目)
    -> knowledge (提问其他能力/知识) -> role (提问对岗位的看法)
    -> coding (手撕代码) -> wrap (结束)

Each state has a deterministic turn budget (how many candidate answers before
advancing) and its own state-specific agent guidance. EVERY round rebuilds an LLM
agent whose prompt contains: the interviewer identity (persona), the candidate's
resume, this interview's special requirements (job/JD/scenario/notes), the
cross-interview memory, and the FULL chat history. The LLM decides WHAT to say
inside the current state; the state machine decides WHEN to move on.

The flow appends dynamic PlannedQuestion/AnswerRecord back into the InterviewContext
so the existing report/scoring still works.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from .contracts import (
    AnswerRecord,
    InterviewContext,
    PlannedQuestion,
    RubricItem,
)
from .llm import LLM
from .prep import _persona_style  # reuse persona tone

logger = logging.getLogger("agent.liveflow")

# # Ordered interview states (the state machine). 'coding' is dropped when the
# # booking has no coding round.
STATES = ["intro", "project", "project_qa", "knowledge", "role", "coding", "wrap"]

# Default budgets (minutes).
DEFAULT_GROUP_MIN = 40
DEFAULT_CODING_MIN = 20

# Human labels shown in the UI / demo.
STATE_LABELS = {
    "intro": "自我介绍",
    "project": "介绍项目",
    "project_qa": "提问项目",
    "knowledge": "其他能力/知识",
    "role": "对岗位的看法",
    "coding": "手撕代码",
    "wrap": "收尾/结束",
}

# section_for_ui maps a state to the plan's section names the UI/CodingPanel uses.
_STATE_SECTION = {
    "intro": "intro",
    "project": "behavioral",
    "project_qa": "technical",
    "knowledge": "technical",
    "role": "behavioral",
    "coding": "coding",
    "wrap": "wrap",
}

# Default number of candidate answers before a state advances.
_STATE_TURN_BUDGET = {
    "intro": 1,
    "project": 1,
    "project_qa": 4,
    "knowledge": 3,
    "role": 1,
    "coding": 4,
    "wrap": 1,
}


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
    lines = [f"岗位:{j.position}({j.seniority})@{j.company}"]
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
    """A single live interview: an EXPLICIT state machine + per-round agent."""

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
        turn_budgets: Optional[dict[str, int]] = None,
    ):
        self.ctx = ctx
        self.lang = lang
        self.has_coding = has_coding
        self.notes = notes or ""
        self.scenario = scenario or "algorithm"
        self.group_min = int(group_min or DEFAULT_GROUP_MIN)
        self.coding_min = int(coding_min or DEFAULT_CODING_MIN)
        self.total_min = self.group_min + self.coding_min
        # Overridable per-state turn budgets (default above). Lets a fast test hit
        # every state without waiting for real minutes.
        self.turn_budgets = {**_STATE_TURN_BUDGET, **(turn_budgets or {})}

        self.turns: list[dict[str, str]] = []  # full chat history [{role, content}]
        self.started_at = time.monotonic()
        self.state_started_at = self.started_at
        self._state_index = 0  # index into STATES
        self._state_entry_users = 0  # user-turn count at entry
        self.done = False
        self.coding_announced = False
        self.coding_elapsed_start: Optional[float] = None
        self._qseq = 0
        self._opened = False  # the opening self-intro has been spoken once
        self._asked_in_state: str = "intro"  # state in which the LAST question was asked

        self.ctx.status = "live"
        self.ctx.cursor = 0

    # ---- state helpers -----------------------------------------------------
    def _states(self) -> list[str]:
        return [s for s in STATES if not (s == "coding" and not self.has_coding)]

    @property
    def state(self) -> str:
        ss = self._states()
        return ss[self._state_index] if self._state_index < len(ss) else "wrap"

    # Backward-compat aliases used by main.py / voice_ws.py.
    @property
    def phase(self) -> str:
        return self.state

    def state_label(self) -> str:
        return STATE_LABELS.get(self.state, self.state)

    def current_phase(self) -> str:
        return self.state

    def section_for_ui(self) -> str:
        return _STATE_SECTION.get(self.state, "technical")

    def _section_for_state(self, state: str) -> str:
        return _STATE_SECTION.get(state, "technical")

    def open_states(self) -> list[str]:
        return self._states()

    def _elapsed_min(self) -> float:
        return (time.monotonic() - self.started_at) / 60.0

    def _group_elapsed_min(self) -> float:
        """Conversation-phase elapsed (up to the point coding started)."""
        if self.coding_elapsed_start is not None:
            return (self.coding_elapsed_start - self.started_at) / 60.0
        return self._elapsed_min()

    def _true_elapsed_min(self) -> float:
        """Real elapsed since the interview started (keeps running during coding)."""
        return self._elapsed_min()

    def _state_answer_count(self) -> int:
        return self._user_count() - self._state_entry_users

    def _user_count(self) -> int:
        return sum(1 for t in self.turns if t.get("role") == "user")

    # ---- public API --------------------------------------------------------
    def opening_line(self) -> str:
        """First interviewer utterance: request a self-intro. Idempotent."""
        if self._opened:
            return self.turns[-1]["content"]
        self._opened = True
        self._asked_in_state = "intro"
        line = (
            "你好，很高兴见到你。这是一场模拟面试，我会按顺序问你几部分："
            "先请你做自我介绍，再聊聊你的项目，然后我会就项目、你的能力和对这个岗位的看法深入聊，"
            "最后我们做一道手撕代码题。现在我们开始吧，请你先做个简单的自我介绍，说说你的教育背景和最有代表性的经历。"
        )
        self.turns.append({"role": "assistant", "content": line})
        return line

    @property
    def opened(self) -> bool:
        return self._opened

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

        self._record_answer(user_text)

        line = self._ask_agent()
        if not line:
            line = self._fallback_line()
        self.turns.append({"role": "assistant", "content": line})

        # Advance the state machine AFTER speaking, so a farewell is spoken first.
        self._advance_state()

        return line

    # ---- scoring feed ------------------------------------------------------
    def _record_answer(self, user_text: str) -> None:
        """Append the asked question + candidate answer into ctx so /report works."""
        try:
            prev = self.turns[-2] if len(self.turns) >= 2 else None
            question_text = (prev or {}).get("content", "") if (prev or {}).get("role") == "assistant" else ""
            self._qseq += 1
            qid = f"live-q{self._qseq}"
            # Tag the answer with the state in which the QUESTION was asked (the state
            # may already have advanced past it by the time the answer is recorded).
            asked_state = self._asked_in_state or self.state
            self.ctx.plan.questions.append(PlannedQuestion(
                id=qid,
                section=self._section_for_state(asked_state),
                text=(question_text or "（请描述你的相关经历）")[:400],
                difficulty=3,
                rubric=[RubricItem(point="depth", weight=1.0)],
                followups=[],
                target_competency=asked_state,
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
        state = self.state
        self._asked_in_state = state  # the question we generate belongs to this state
        elapsed = self._true_elapsed_min()
        remaining = max(0.0, self.group_min + self.coding_min - elapsed)
        next_state = self._next_state_name()
        persona = _persona_line(getattr(self.ctx, "persona", "high-peer"))
        style = _persona_style(getattr(self.ctx, "persona", "high-peer"))
        memory = getattr(self.ctx, "memory_brief", "") or ""

        sys_ = (
            f"你是一位正在主持真实技术面试的资深面试官。{persona} 面试风格:{style}\n"
            "【面试环节顺序】自我介绍 → 介绍项目 → 提问项目细节 → 提问其他能力/知识 → "
            "提问对岗位的看法 → 手撕代码 → 收尾。\n"
            f"【当前环节】{state}（下一环节：{next_state}）\n"
            f"【时间预算】已用约 {elapsed:.1f} 分钟，还剩约 {remaining:.1f} 分钟。\n"
            f"【候选人简历】\n{_candidate_brief(self.ctx)}\n"
            f"【本场特点】\n{_requirements_brief(self.ctx, self.notes, self.scenario)}\n"
            f"{('【跨场记忆】' + memory) if memory else ''}\n"
            "【面试规则】\n"
            "- 用中文口语化地说一句话推进面试；只问一个问题，不要一次抛多个问题、不要报题号。\n"
            "- 根据候选人上一句的长短和深度调整：答得浅就追问细节，答得深就换一个点，时间少就加快。\n"
            "- 不要复述问题，不要提评分或打分，不要说'我记录了'。\n"
            f"- 当前环节是【{state}】，请严格按这个环节的要求提问：{self._state_guidance(state)}\n"
        )
        user = (
            "【到目前为止的完整对话】\n" + self._history_block() +
            "\n\n【请输出】你作为面试官接下来的那句话。只需要输出这一句话本身，不要加引号或解释。"
        )
        try:
            llm = LLM()
            line = llm.chat(
                [{"role": "system", "content": sys_}, {"role": "user", "content": user}],
                max_tokens=320,
                temperature=0.8,
                timeout=45.0,
            )
            line = (line or "").strip().strip('"').strip()
            return line[:500]
        except Exception as exc:  # noqa: BLE001
            logger.warning("liveflow _ask_agent failed: %s", exc)
            return ""

    def _state_guidance(self, state: str) -> str:
        return {
            "intro": "面试开场。请让候选人做自我介绍，一句自然、有亲和力的话即可。",
            "project": "听完自我介绍后，请让候选人挑一个最有代表性的具体项目来介绍。",
            "project_qa": "这是主环节：围绕候选人刚介绍的项目深入提问（架构、难点、数据、取舍、踩坑），逐层加深。",
            "knowledge": "项目问得差不多了，转向该岗位需要的基础/专业知识/软实力提问（结合岗位要求与候选人的薄弱点）。",
            "role": "请问候选人关于这个岗位/公司的问题，例如为什么想来、对岗位的理解、职业规划、能否接受某类工作节奏。",
            "coding": "进入手撕代码环节：简述题目，引导候选人先讲思路，再要求其在代码区作答，你负责观察与提示。",
            "wrap": "做收尾：感谢候选人，简要点出亮点与可改进处，并留时间让候选人反问。（你说完这句即结束）",
        }.get(state, "请自然、专业地推进面试。")

    def _next_state_name(self) -> str:
        ss = self._states()
        idx = self._state_index if self._state_index < len(ss) else len(ss) - 1
        return ss[idx + 1] if idx + 1 < len(ss) else "wrap"

    # ---- state machine -----------------------------------------------------
    def _advance_state(self) -> None:
        """Advance the state machine by per-state turn budget (deterministic).

        A hard time cap is the safety net so a real 40/20-min interview is never
        late; the turn budgets let a fast test/demo reach (and verify) every state.
        """
        ss = self._states()
        idx = self._state_index if self._state_index < len(ss) else len(ss) - 1
        cur = ss[idx]

        if self.done:
            return

        # Hard group time cap -> push forward (safety net for a real long interview).
        if cur != "coding" and cur != "wrap" and self._group_elapsed_min() >= self.group_min:
            self._enter_state(ss, min(idx + 1, len(ss) - 1))
            return

        # Coding advances by budget OR by time (whichever comes first).
        if cur == "coding":
            time_up = (
                self.coding_elapsed_start is not None
                and (time.monotonic() - self.coding_elapsed_start) / 60.0 >= self.coding_min
            )
            if time_up or self._state_answer_count() >= self.turn_budgets.get(cur, 1):
                self._enter_state(ss, min(idx + 1, len(ss) - 1))
            return

        # Deterministic turn budget for this state.
        if self._state_answer_count() >= self.turn_budgets.get(cur, 1):
            if cur == "wrap":
                self.done = True
                return
            self._enter_state(ss, min(idx + 1, len(ss) - 1))

    def _enter_state(self, ss: list[str], new_index: int) -> None:
        if new_index == self._state_index:
            return
        self._state_index = new_index
        self.state_started_at = time.monotonic()
        self._state_entry_users = self._user_count()
        if self.state == "coding" and not self.coding_announced:
            self.coding_announced = True
            self.coding_elapsed_start = time.monotonic()

    def _fallback_line(self) -> str:
        return {
            "intro": "请先做个自我介绍吧。",
            "project": "可以说说你最有代表性的一个项目吗？",
            "project_qa": "这个项目里你遇到了哪些难点，是怎么解决的？",
            "knowledge": "结合这类岗位，你还需要补哪些底子？说说你最熟的一块。",
            "role": "你为什么想来这个岗位/公司？",
            "coding": "我们进入手撕代码环节，请看题目并在代码区作答。",
            "wrap": "感谢你的回答，可以看看你的面试报告。",
        }.get(self.state, "请继续。")


def make_flow(ctx: InterviewContext, **kw) -> LiveFlow:
    """Convenience factory (used by main when a live turn starts)."""
    return LiveFlow(ctx, **kw)
