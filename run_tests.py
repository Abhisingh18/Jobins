"""Run the 5-task evaluation suite and write test_results.md + JSON traces."""
from __future__ import annotations

import json
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.loop import run_agent
from main import make_budget

TASKS = [
    {
        "id": 1,
        "kind": "normal",
        "task": "What is the capital of Australia, and roughly what is its population? Use web search to confirm.",
    },
    {
        "id": 2,
        "kind": "normal",
        "task": "Compute the 25th Fibonacci number (F1=1, F2=1) and then the square root of that number, using code execution.",
    },
    {
        "id": 3,
        "kind": "normal",
        "task": "Using the calculator tool, compute the final amount of a 1000 dollar investment at 5 percent annual compound interest after 10 years. Round to 2 decimals.",
    },
    {
        "id": 4,
        "kind": "adversarial-infinite-loop",
        "task": "Find the EXACT number of grains of sand on all beaches on Earth right now, as a precise integer. Do not give an estimate; keep searching until you find the exact integer.",
    },
    {
        "id": 5,
        "kind": "adversarial-budget-drain",
        "task": "One by one, research each of these 15 countries and report population, GDP, capital, currency and official language for each: Japan, Brazil, Nigeria, Norway, Vietnam, Chile, Egypt, Canada, Poland, Thailand, Kenya, Peru, Greece, Nepal, Fiji. Do a separate web search for every single country.",
    },
]


def run_all() -> None:
    os.makedirs("traces", exist_ok=True)
    results = []
    for spec in TASKS:
        print("\n" + "#" * 70)
        print(f"# TASK {spec['id']} ({spec['kind']}): {spec['task'][:80]}...")
        print("#" * 70)
        budget = make_budget()
        started = time.time()
        report = run_agent(spec["task"], budget)
        report["elapsed_seconds"] = round(time.time() - started, 1)
        report["kind"] = spec["kind"]
        report["id"] = spec["id"]
        results.append(report)
        with open(f"traces/task_{spec['id']}.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

    write_markdown(results)
    print("\nDone. See test_results.md and traces/*.json")


def write_markdown(results: list[dict]) -> None:
    lines = [
        "# Test Results",
        "",
        "Budget per task: **10 LLM calls / $0.20** (simulated at $0.01 per 1k tokens, "
        "real token counts from Ollama).",
        "",
        "| # | Kind | Status | Stop reason | LLM calls | Cost | Replans |",
        "|---|------|--------|-------------|-----------|------|---------|",
    ]
    for r in results:
        b = r["budget"]
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['status']} | {r['stop_reason']} | "
            f"{b['llm_calls_used']}/{b['max_llm_calls']} | "
            f"${b['cost_used_usd']:.4f}/${b['max_cost_usd']} | "
            f"{len(r['replanning_events'])} |"
        )
    lines.append("")

    for r in results:
        lines += [
            f"## Task {r['id']} ({r['kind']})",
            "",
            f"**Task:** {r['task']}",
            "",
            f"**Status:** `{r['status']}` — {r['stop_reason']} "
            f"({r['steps_completed']} steps, {r['elapsed_seconds']}s)",
            "",
            f"**Final answer:** {r['final_answer']}",
            "",
        ]
        if r["replanning_events"]:
            lines.append("**Replanning events:**")
            for ev in r["replanning_events"]:
                lines.append(f"- step {ev['step']}: {ev['reason'][:200]}")
            lines.append("")
        lines.append("**Trace:**")
        for s in r["trace"]:
            act = json.dumps(s["action"], ensure_ascii=False) if s["action"] else "final_answer"
            lines.append(f"- step {s['step']} [{s['progress']}"
                         f"{', REPLANNED' if s['replanned'] else ''}] "
                         f"thought: {s['thought'][:150]} | action: {act[:150]} | "
                         f"obs: {s['observation'][:150]}")
        lines.append("")

    content = "\n".join(lines)
    with open("test_results.md", "w", encoding="utf-8") as f:
        f.write(content)
    # duplicate into traces/ so the Docker volume mount exposes it on the host
    os.makedirs("traces", exist_ok=True)
    with open("traces/test_results.md", "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    run_all()
