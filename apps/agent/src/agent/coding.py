"""Hand-code coding round: the agent loads the offline problem and judges the
candidate's code with the LLM (static analysis + hint ladder). The AI interviewer
"sees" the code because the code text is passed to the judge in full — no live
code-execution engine needed for v1 (Piston is a P2 option)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .llm import LLM


def load_problem(slug: str | None) -> dict | None:
    """Find a problem in the offline bank by title_slug."""
    if not slug:
        return None
    path = Path(__file__).resolve().parent / "data" / "problems.json"
    try:
        d = json.loads(path.read_text())
        probs = d.get("problems", d) if isinstance(d, dict) else d
        for p in probs:
            if p.get("title_slug") == slug:
                return p
    except Exception:
        pass
    return None


def judge_code(problem: dict | None, code: str, language: str = "python") -> dict:
    code = code or ""
    if not code.strip():
        return {"status": "incomplete", "score": 0, "issues": [],
                "hint_level": 0, "next_hint": "先写下你的思路或代码，我帮你看看。", "speech": "先写下你的思路或代码吧。"}

    title = (problem or {}).get("title", "")
    desc = (problem or {}).get("description", "")
    examples = json.dumps((problem or {}).get("examples", [])[:2], ensure_ascii=False)
    sys_ = ("You are a senior coding interviewer. Evaluate the candidate's solution to the given problem. "
            "Only judge the provided code; do not invent missing parts. Never reveal a full solution or AC code. "
            "Return ONLY JSON: {status(correct|partial|incorrect|incomplete), score(0-5), "
            "issues[{type,line,detail}], hint_level(0-2), next_hint, speech(<=2 sentences, target language)}.")
    user = (f"Problem: {title}\nDescription: {desc}\nExamples: {examples}\nLanguage: {language}\n"
            f"Candidate code:\n```{language}\n{code}\n```\n\nJudge it.")
    try:
        j = LLM().chat_json([{"role": "system", "content": sys_}, {"role": "user", "content": user}], max_tokens=1024)
    except Exception:
        return {"status": "incomplete", "score": 2, "issues": [], "hint_level": 0,
                "next_hint": "我这边暂时无法分析，请再检查一下代码。", "speech": "我这边暂时无法分析，再检查一下代码。"}

    status = j.get("status") if j.get("status") in ("correct", "partial", "incorrect", "incomplete") else "partial"
    score = max(0, min(5, int(j.get("score", 2))))
    issues = j.get("issues", []) if isinstance(j.get("issues"), list) else []
    return {
        "status": status,
        "score": score,
        "issues": [{"type": i.get("type", ""), "line": i.get("line"), "detail": i.get("detail", "")} for i in issues if isinstance(i, dict)],
        "hint_level": max(0, min(2, int(j.get("hint_level", 0)))),
        "next_hint": str(j.get("next_hint", "")),
        "speech": str(j.get("speech", ""))[:300],
    }
