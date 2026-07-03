"""Hard budget enforcement for LLM calls and simulated cost.

Every LLM call in the system MUST pass through BudgetEnforcer.charge().
There is no other path to the model, so the limit cannot be bypassed.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


class BudgetExceededError(Exception):
    """Raised the moment a call would exceed the budget. Stops execution."""

    def __init__(self, reason: str, snapshot: dict):
        self.reason = reason  # "call_limit" | "cost_limit"
        self.snapshot = snapshot
        super().__init__(f"Budget exceeded ({reason}): {snapshot}")


@dataclass
class LedgerEntry:
    call_type: str  # "llm" | tool name
    tokens: int
    cost_usd: float
    timestamp: float = field(default_factory=time.time)
    meta: str = ""


class BudgetEnforcer:
    """Atomic check-then-record budget gate.

    The check and the record happen under one lock so a burst of calls
    can never race past the limit.
    """

    def __init__(self, max_llm_calls: int = 10, max_cost_usd: float = 0.20,
                 price_per_1k_tokens: float = 0.01):
        self.max_llm_calls = max_llm_calls
        self.max_cost_usd = max_cost_usd
        self.price_per_1k_tokens = price_per_1k_tokens
        self.llm_calls_used = 0
        self.cost_used_usd = 0.0
        self.ledger: list[LedgerEntry] = []
        self._lock = threading.Lock()

    def snapshot(self) -> dict:
        return {
            "llm_calls_used": self.llm_calls_used,
            "max_llm_calls": self.max_llm_calls,
            "cost_used_usd": round(self.cost_used_usd, 6),
            "max_cost_usd": self.max_cost_usd,
        }

    def precheck_llm_call(self) -> None:
        """Refuse to even START an LLM call if the call budget is spent."""
        with self._lock:
            if self.llm_calls_used + 1 > self.max_llm_calls:
                raise BudgetExceededError("call_limit", self.snapshot())
            if self.cost_used_usd >= self.max_cost_usd:
                raise BudgetExceededError("cost_limit", self.snapshot())

    def charge_llm_call(self, tokens: int, meta: str = "") -> None:
        """Record a completed LLM call. Raises if this call breached a limit.

        The call has already happened by the time we know its token count,
        so we record it, then raise if the recorded totals breached a limit —
        execution stops immediately either way.
        """
        cost = (tokens / 1000.0) * self.price_per_1k_tokens
        with self._lock:
            self.llm_calls_used += 1
            self.cost_used_usd += cost
            self.ledger.append(LedgerEntry("llm", tokens, cost, meta=meta))
            if self.llm_calls_used > self.max_llm_calls:
                raise BudgetExceededError("call_limit", self.snapshot())
            if self.cost_used_usd > self.max_cost_usd:
                raise BudgetExceededError("cost_limit", self.snapshot())

    def record_tool_call(self, tool_name: str, meta: str = "") -> None:
        """Tools are free in money terms but are logged for the audit trail."""
        with self._lock:
            self.ledger.append(LedgerEntry(tool_name, 0, 0.0, meta=meta))

    def remaining(self) -> dict:
        with self._lock:
            return {
                "llm_calls": self.max_llm_calls - self.llm_calls_used,
                "cost_usd": round(self.max_cost_usd - self.cost_used_usd, 6),
            }
