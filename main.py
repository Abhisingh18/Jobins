"""Entry point.

Usage:
    python main.py "your task here"     # run one task
    python main.py --all-tests          # run the 5-task evaluation suite
"""
from __future__ import annotations

import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.budget import BudgetEnforcer
from agent.loop import run_agent


def make_budget() -> BudgetEnforcer:
    return BudgetEnforcer(
        max_llm_calls=int(os.environ.get("MAX_LLM_CALLS", "10")),
        max_cost_usd=float(os.environ.get("MAX_COST_USD", "0.20")),
        price_per_1k_tokens=float(os.environ.get("MOCK_PRICE_PER_1K_TOKENS", "0.01")),
    )


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--all-tests":
        from run_tests import run_all
        run_all()
        return

    task = " ".join(sys.argv[1:])
    report = run_agent(task, make_budget())
    print("\n" + "=" * 60)
    print("FINAL REPORT")
    print("=" * 60)
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
