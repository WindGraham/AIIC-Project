"""CandidateAgent — 用 DeepSeek 扮演求职者的"候选人"一侧。

双 agent 互聊 harness 的测试数据生成器：给定 profile（职级/风格/强弱/技能/
会不会被带偏/公司岗位 JD），`.respond(question, transcript)` 生成贴合面试的
候选人回答。weak/vague 回答自然含糊，strong 回答结构清晰带术语，让 Judge 能
量化区分。

- 默认真实走 DeepSeek（agent.llm.LLM）。
- 任何 LLM 失败都会降级到确定性占位回答，harness 永不因候选人侧崩溃。
- off_topic 由 seed 控制的随机数决定，可复现。
"""

from __future__ import annotations

import random
from typing import Any

from agent.llm import LLM

_LEVEL_ZH = {
    "junior": "应届生/准应届生，工作 0-1 年，基础知识扎实但实战经验有限",
    "mid": "3 年左右后端研发经验，能独立负责模块设计与开发",
    "senior": "5-8 年后端研发经验，主导过大型系统设计与重构",
    "staff": "10 年+ 资深专家，技术负责人，主导过架构级演进与团队技术方向",
}

_STYLE_ZH = {
    "concise": "回答简洁直接，2-4 句话讲清要点，不啰嗦，不堆砌客套话",
    "verbose": "回答详细，分点展开，主动补充背景、权衡与细节，篇幅较长",
    "vague": "回答含糊空泛，多用「大概/可能/不太确定/记不太清了」等模糊措辞，回避具体数字与细节",
}

_STRENGTH_ZH = {
    "strong": (
        "技术水平强：先说结论再展开，使用准确的技术术语，给出具体的量化指标"
        "（QPS/耗时/数据量/优化倍数等），主动讲清设计权衡与备选方案"
    ),
    "mid": "技术水平中等：能讲到主要要点和部分细节，术语使用一般，量化指标偶尔给出",
    "weak": "技术水平偏弱：理解停留在表面，很少使用术语，缺少深度与细节，量化指标基本说不出",
}


def _default_profile() -> dict:
    return {
        "name": "候选人",
        "level": "mid",
        "style": "concise",
        "strength": "mid",
        "resume_skills": [],
        "off_topic_prob": 0.0,
        "company": "",
        "position": "",
        "jd": "",
        "resume": "",
        "seed": 42,
    }


class CandidateAgent:
    """LLM 扮演求职者。profile 见 _default_profile()；缺省字段自动补齐。"""

    def __init__(self, profile: dict[str, Any], llm: LLM | None = None) -> None:
        merged = _default_profile()
        merged.update({k: v for k, v in profile.items() if v is not None})
        self.profile = merged
        self.llm = llm or LLM()
        self._rng = random.Random(int(merged["seed"]))

    # ------------------------------------------------------------------
    def respond(self, question: str, transcript_so_far: Any) -> str:
        """返回候选人本轮回答。question 是面试官刚问的问题。"""
        p = self.profile
        off_topic = self._rng.random() < float(p.get("off_topic_prob", 0.0))
        system = self._system_prompt(off_topic=off_topic)
        user = self._user_prompt(question, transcript_so_far)
        try:
            out = self.llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=self._max_tokens(),
                temperature=self._temperature(),
                timeout=90.0,
            )
            text = (out or "").strip()
            if text:
                return text
        except Exception as exc:  # noqa: BLE001 — harness 永不因 LLM 失败而崩
            self._last_error = repr(exc)
        return self._fallback(question)

    # ------------------------------------------------------------------
    def _system_prompt(self, *, off_topic: bool) -> str:
        p = self.profile
        level = p.get("level", "mid")
        style = p.get("style", "concise")
        strength = p.get("strength", "mid")
        skills = "、".join(p.get("resume_skills", []) or ["基础研发技能"])
        lines = [
            f"你是一名正在参加真实面试的求职者：{p.get('name', '候选人')}。",
            f"你的背景：{_LEVEL_ZH.get(level, _LEVEL_ZH['mid'])}。",
            f"你的核心技能：{skills}。",
            f"面试的公司/岗位：{p.get('company') or '(未指明)'} · {p.get('position') or '(未指明)'}。",
        ]
        if p.get("jd"):
            lines.append(f"岗位 JD（你在意其中提到的要求）：{p['jd']}")
        if p.get("resume"):
            lines.append(f"你的简历摘要：{p['resume'][:400]}")
        lines.append(f"回答风格：{_STYLE_ZH.get(style, _STYLE_ZH['concise'])}。")
        lines.append(f"你的真实水平：{_STRENGTH_ZH.get(strength, _STRENGTH_ZH['mid'])}。")
        if off_topic:
            lines.append(
                "【本回合特殊要求】你有点紧张跑题了：回答时自然地带入一段与本题关系不大的内容"
                "（比如提到大学的社团经历或生活琐事），再勉强绕回问题本身，让回答显得不够聚焦。"
            )
        lines.append(
            "只输出候选人的回答内容本身：不要输出『面试官：』等角色前缀，不要解释你的回答思路，"
            "不要重复问题，不要输出额外字段。用中文回答。"
        )
        return "\n".join(lines)

    def _user_prompt(self, question: str, transcript_so_far: Any) -> str:
        mem = self._recent_memory(transcript_so_far)
        return (
            f"面试官刚才的问题是：\n{question}\n\n"
            f"对话记忆（此前几轮，供你保持一致，无需复述）：\n{mem or '（这是第一问，还没有前文）'}\n\n"
            "请给出你的回答："
        )

    @staticmethod
    def _recent_memory(transcript_so_far: Any) -> str:
        """把 transcript 压缩成最近几轮的短记忆文本。

        mock brain 传 list[dict]，真实 pipeline 传 str（"Q: ...\nA: ..."），
        两种都兼容。
        """
        if not transcript_so_far:
            return ""
        if isinstance(transcript_so_far, str):
            return "\n".join(transcript_so_far.splitlines()[-12:])[:1000]
        entries = list(transcript_so_far)[-6:]
        parts = []
        for e in entries:
            role = e.get("role", "?") if isinstance(e, dict) else "?"
            text = (e.get("text") if isinstance(e, dict) else str(e)).strip()
            if not text:
                continue
            label = "面试官" if role == "interviewer" else ("候选人" if role == "candidate" else role)
            parts.append(f"{label}：{text[:180]}")
        joined = "\n".join(parts)
        return joined[:1000]

    def _max_tokens(self) -> int:
        return 400 if self.profile.get("style") == "verbose" else 200

    def _temperature(self) -> float:
        style = self.profile.get("style")
        strength = self.profile.get("strength")
        if style == "vague":
            return 0.9
        if strength == "strong":
            return 0.6
        return 0.4

    # ------------------------------------------------------------------
    def _fallback(self, question: str) -> str:
        """确定性占位回答（LLM 不可用/超时/报错时），保证 harness 离线也能跑。"""
        p = self.profile
        name = p.get("name", "候选人")
        skills = "、".join(p.get("resume_skills", [])[:3]) or "相关技术"
        style = p.get("style", "concise")
        if style == "vague":
            return (
                f"嗯……这个问题我大概有点了解，但细节记不太清了。核心思路应该是从{skills}这些基础出发，"
                "具体方案可能得再查一下资料才能说得更准，不过我理解大方向是没问题的。"
            )
        if style == "verbose":
            return (
                f"好的，我来回答。这个问题涉及{skills}。首先从背景看，我之前的项目里遇到过类似的场景，"
                "当时我们先是分析了业务约束，然后对比了几种主流方案，最终选择了权衡下来最合适的那个；"
                "实现上需要注意边界情况和性能，上线后我们也做了压测和监控，整体效果符合预期。"
                "如果深入一层，我觉得还可以从扩展性和可维护性两个角度再优化。"
            )
        return (
            f"关于这个问题，结合我用{skills}的经验，我理解关键点是先明确目标和约束，再选择合适的技术方案，"
            "并注意边界与性能。具体的细节我在项目里实践过，可以再展开说明。"
        )
