"""Runnable demo for the Researcher module.

Run (from anywhere)::

    cd apps/agent/src/agent/researcher && .venv/bin/python run.py

or (module style, from apps/agent)::

    cd apps/agent && PYTHONPATH=src .venv/bin/python -m agent.researcher.run

Options::

    python run.py --company 字节跳动 --position 后端开发工程师 \\
        --jd "负责支付系统…" --seniority senior --language zh --force
"""

import argparse
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

from agent.researcher import build_job_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Researcher demo: build a JobProfile")
    parser.add_argument("--company", default="字节跳动")
    parser.add_argument("--position", default="后端开发工程师")
    parser.add_argument("--jd", default="负责高并发后端服务的架构设计与研发")
    parser.add_argument("--seniority", default="senior", choices=["junior", "mid", "senior", "staff"])
    parser.add_argument("--language", default="zh", choices=["zh", "en"])
    parser.add_argument("--force", action="store_true", help="bypass the 90-day cache")
    args = parser.parse_args()

    t0 = time.time()
    profile = build_job_profile(
        args.company,
        args.position,
        args.jd,
        args.seniority,
        args.language,
        force=args.force,
    )
    dt = time.time() - t0

    print(json.dumps(profile.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print("-" * 72)
    print(
        f"OK in {dt:.1f}s: {profile.position} @ {profile.company} "
        f"| confidence={profile.confidence:.2f} | missing_company_info={profile.missing_company_info} "
        f"| sources={len(profile.sources)} | likely_questions={len(profile.likely_questions)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
