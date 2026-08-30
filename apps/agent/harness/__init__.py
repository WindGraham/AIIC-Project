"""Run-entry shim — 让 `cd apps/agent && .venv/bin/python -m harness.run` 可直接运行。

真实实现位于 `src/agent/harness/`（本 shim 负责把 `src` 加入 sys.path 并转发）。
这是为了让验收命令在 `apps/agent` 目录下以顶层模块方式运行；代码本体不在这里。
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from agent.harness import *  # noqa: E402,F401,F403
from agent.harness import __all__ as _all

__all__ = list(_all)
