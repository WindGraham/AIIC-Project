"""Acceptance test for the Researcher module.

Runnable two ways (both hit the real provider stack + DeepSeek LLM):

* pytest::

    cd apps/agent && .venv/bin/python -m pytest src/agent/researcher/test_researcher.py -v

* plain module run (no pytest needed)::

    cd apps/agent && PYTHONPATH=src .venv/bin/python -m agent.researcher.test_researcher

or simply::

    cd apps/agent/src/agent/researcher && .venv/bin/python test_researcher.py

Acceptance: returns a valid ``JobProfile`` with ``summary``/``confidence`` set,
``sources`` possibly empty and ``missing_company_info`` possibly True when the
network is blocked — but NEVER raises.
"""

import json
import os
import sys
import time
from pathlib import Path

# --- bootstrap: make `agent` importable + load apps/agent/.env regardless of cwd
_SRC = Path(__file__).resolve().parents[2]  # apps/agent/src
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_env_file = _SRC.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and not os.environ.get(k):
            os.environ[k] = v

import logging  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

from agent.researcher import JobProfile, build_job_profile  # noqa: E402

DEMO_INPUT = ("字节跳动", "后端开发工程师", "负责…", "senior", "zh")


def _run_demo() -> JobProfile:
    """Run the acceptance scenario and print the resulting JobProfile."""
    company, position, jd, seniority, language = DEMO_INPUT
    t0 = time.time()
    profile = build_job_profile(company, position, jd, seniority, language)
    dt = time.time() - t0

    print("\n" + "=" * 72)
    print(f"Researcher acceptance test  ({dt:.1f}s)")
    print("=" * 72)
    print(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print("-" * 72)
    print(
        f"missing_company_info={profile.missing_company_info}  "
        f"confidence={profile.confidence:.2f}  sources={len(profile.sources)}  "
        f"likely_questions={len(profile.likely_questions)}"
    )
    return profile


def test_researcher_demo() -> None:
    """Acceptance: never raises, returns a JobProfile with summary/confidence set."""
    profile = _run_demo()
    # acceptance assertions (plain asserts -> pytest compatible, no pytest dep)
    assert isinstance(profile, JobProfile), "must return a JobProfile"
    assert profile.summary, "summary must have a value"
    assert 0.0 <= profile.confidence <= 1.0, "confidence must be a 0..1 float"
    assert isinstance(profile.sources, list), "sources must be a list (may be empty)"
    assert isinstance(profile.likely_questions, list), "likely_questions must be a list"
    print("PASS: test_researcher_demo")


def main() -> int:
    try:
        _run_demo()
        return 0
    except Exception as exc:  # noqa: BLE001 - report, do not traceback-hang
        print(f"FAIL: researcher test raised: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
