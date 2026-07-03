"""ReAct planning loop with tiered reflection and forced replanning.

Loop shape:  THINK (LLM) -> ACT (tool) -> OBSERVE -> REFLECT -> repeat/finish

Reflection is tiered to conserve budget:
  Tier 1 (free, deterministic): tool errors, empty results, and repeated
          identical actions are flagged as no-progress by code, not the LLM.
  Tier 2 (piggybacked): the next THINK call must include a `progress_check`
          field, so LLM-side reflection costs zero extra calls.

When no-progress is detected, a REPLAN notice is injected into the
conversation and the step is marked `replanned` in the trace.
"""
from __future__ import annotations

import json

from .budget import BudgetEnforcer, BudgetExceededError
from .llm import LLMError, OllamaClient
from .prompts import REPLAN_MESSAGE, SYSTEM_PROMPT
from .state import AgentState, StepRecord
from .tools import TOOLS, tool_catalog

MAX_STEPS = 12  # safety rail; the budget almost always triggers first
MAX_OBS_CHARS = 1500


class LoopDetector:
    """Flags the agent as stuck when it repeats the same (tool, args) call."""

    def __init__(self):
        self.seen: list[str] = []

    def signature(self, action: dict) -> str:
        return json.dumps(
            {"tool": action.get("tool"), "args": action.get("args", {})},
            sort_keys=True,
        )

    def is_repeat(self, action: dict) -> bool:
        return self.signature(action) in self.seen

    def record(self, action: dict) -> None:
        self.seen.append(self.signature(action))


def run_agent(task: str, budget: BudgetEnforcer, verbose: bool = True) -> dict:
    state = AgentState(task=task)
    llm = OllamaClient(budget)
    detector = LoopDetector()
    messages: list[dict] = [{"role": "user", "content": f"TASK: {task}"}]

    def log(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    try:
        for step_no in range(1, MAX_STEPS + 1):
            remaining = budget.remaining()
            system = SYSTEM_PROMPT.format(
                tool_catalog=tool_catalog(),
                calls_left=remaining["llm_calls"],
                cost_left=remaining["cost_usd"],
            )
            # --- THINK ---
            try:
                decision = llm.chat_json(
                    [{"role": "system", "content": system}] + messages,
                    meta=f"think-step-{step_no}",
                )
            except LLMError as exc:
                # Malformed output / model hiccup: one retry message, still budgeted.
                log(f"  [!] LLM error at step {step_no}: {exc}")
                messages.append({
                    "role": "user",
                    "content": "Your last reply was invalid. Reply with ONE valid "
                               "JSON object exactly matching the required format.",
                })
                continue

            thought = str(decision.get("thought", ""))
            progress_check = str(decision.get("progress_check", "n/a"))
            action = decision.get("action")
            final_answer = decision.get("final_answer")
            log(f"\n[step {step_no}] THINK: {thought}")
            log(f"           progress_check: {progress_check}")

            # --- FINISH? ---
            if final_answer:
                state.best_known_answer = str(final_answer)
                state.status = "completed"
                state.stop_reason = "agent_finished"
                state.steps.append(StepRecord(
                    step=step_no, thought=thought, action=None,
                    observation="(final answer given)", progress="progress",
                ))
                log(f"           FINAL ANSWER: {state.best_known_answer}")
                break

            if not action or not isinstance(action, dict) or not action.get("tool"):
                messages.append({
                    "role": "user",
                    "content": "You gave neither a valid action nor a final_answer. "
                               "Pick one now.",
                })
                continue

            tool_name = action.get("tool", "")
            args = action.get("args", {}) or {}

            # --- Tier-1 reflection BEFORE acting: repeated identical action ---
            if detector.is_repeat(action):
                reason = (f"you already ran {tool_name} with identical arguments; "
                          f"repeating it cannot yield new information")
                log(f"  [LOOP DETECTED] {reason} -> forcing replan")
                remaining = budget.remaining()
                messages.append({"role": "user", "content": REPLAN_MESSAGE.format(
                    reason=reason, calls_left=remaining["llm_calls"],
                    cost_left=remaining["cost_usd"])})
                state.steps.append(StepRecord(
                    step=step_no, thought=thought, action=action,
                    observation="(blocked: repeated identical action)",
                    progress="no_progress", replanned=True, replan_reason=reason,
                ))
                continue

            # --- ACT ---
            if tool_name not in TOOLS:
                obs = f"TOOL FAILED (INPUT_ERROR): no tool named '{tool_name}'"
                result_success = False
            else:
                detector.record(action)
                budget.record_tool_call(tool_name, meta=json.dumps(args)[:120])
                result = TOOLS[tool_name].execute(**args)
                obs = result.for_llm()[:MAX_OBS_CHARS]
                result_success = result.success
            log(f"           ACT: {tool_name}({json.dumps(args)[:100]})")
            log(f"           OBSERVE: {obs[:200]}")

            # --- Tier-1 reflection AFTER acting: failures / empty results ---
            no_progress = (not result_success) or \
                          obs.strip().startswith("No results found")
            record = StepRecord(
                step=step_no, thought=thought, action=action, observation=obs,
                progress="no_progress" if no_progress else "progress",
            )
            messages.append({"role": "assistant", "content": json.dumps(decision)})

            if no_progress:
                reason = f"the {tool_name} call did not produce useful output: {obs[:150]}"
                remaining = budget.remaining()
                messages.append({"role": "user", "content":
                    f"OBSERVATION: {obs}\n\n" + REPLAN_MESSAGE.format(
                        reason=reason, calls_left=remaining["llm_calls"],
                        cost_left=remaining["cost_usd"])})
                record.replanned = True
                record.replan_reason = reason
                log("  [NO PROGRESS] -> replan notice injected")
            else:
                messages.append({"role": "user", "content": f"OBSERVATION: {obs}"})
                # keep the most recent useful observation as a fallback answer
                state.scratchpad["last_useful_observation"] = obs

            state.steps.append(record)
        else:
            state.status = "partial"
            state.stop_reason = "max_steps_reached"

    except BudgetExceededError as exc:
        # --- GRACEFUL EXIT: report exactly what was completed so far ---
        state.status = "partial" if state.steps else "failed"
        state.stop_reason = f"budget_exceeded:{exc.reason}"
        if not state.best_known_answer:
            state.best_known_answer = (
                "(budget exhausted before a final answer) Best available info: "
                + state.scratchpad.get("last_useful_observation", "none gathered")[:500]
            )
        log(f"\n[BUDGET EXCEEDED] {exc.reason} — stopping cleanly. "
            f"{len(state.steps)} steps completed.")

    if state.status == "running":
        state.status = "partial"
        state.stop_reason = state.stop_reason or "loop_ended_without_answer"

    return state.to_report(budget.snapshot())
