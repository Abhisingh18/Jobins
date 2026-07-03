"""State schema: everything the loop, tools and LLM share flows through here."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Optional


@dataclass
class StepRecord:
    step: int
    thought: str
    action: Optional[dict]  # {"tool": str, "args": dict} or None for final answer
    observation: str
    progress: Literal["progress", "no_progress", "n/a"]
    replanned: bool = False
    replan_reason: str = ""


@dataclass
class AgentState:
    task: str
    steps: list[StepRecord] = field(default_factory=list)
    scratchpad: dict[str, Any] = field(default_factory=dict)
    best_known_answer: Optional[str] = None
    status: Literal["running", "completed", "partial", "failed"] = "running"
    stop_reason: str = ""

    def to_report(self, budget_snapshot: dict) -> dict:
        return {
            "task": self.task,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "final_answer": self.best_known_answer,
            "steps_completed": len(self.steps),
            "replanning_events": [
                {"step": s.step, "reason": s.replan_reason}
                for s in self.steps if s.replanned
            ],
            "budget": budget_snapshot,
            "trace": [asdict(s) for s in self.steps],
        }
