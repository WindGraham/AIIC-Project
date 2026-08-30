"""python -m harness — 等价于 python -m harness.run。"""

from agent.harness.run import main

if __name__ == "__main__":
    raise SystemExit(main())
