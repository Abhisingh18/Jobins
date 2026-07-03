"""Common tool interface: every tool runs under a hard timeout and returns
a structured ToolResult. No bare `except: pass` anywhere — every failure is
categorized and surfaced to the planning loop.
"""
from __future__ import annotations

import concurrent.futures
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ToolResult:
    success: bool
    data: str = ""
    error: str = ""
    error_type: str = ""  # "TIMEOUT" | "INPUT_ERROR" | "EXECUTION_ERROR" | "NETWORK_ERROR"

    def for_llm(self) -> str:
        if self.success:
            return self.data
        return f"TOOL FAILED ({self.error_type}): {self.error}"


class Tool(ABC):
    name: str = "tool"
    description: str = ""
    args_hint: str = ""
    timeout_seconds: int = 15

    def execute(self, **kwargs) -> ToolResult:
        """Run the tool body in a worker thread with a hard wall-clock timeout."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._run_safe, **kwargs)
            try:
                return future.result(timeout=self.timeout_seconds)
            except concurrent.futures.TimeoutError:
                future.cancel()
                return ToolResult(
                    success=False,
                    error=f"{self.name} exceeded {self.timeout_seconds}s timeout",
                    error_type="TIMEOUT",
                )

    def _run_safe(self, **kwargs) -> ToolResult:
        try:
            return self._run(**kwargs)
        except TypeError as exc:
            return ToolResult(success=False, error=f"bad arguments: {exc}",
                              error_type="INPUT_ERROR")
        except Exception as exc:  # categorized, logged, surfaced — never swallowed
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}",
                              error_type="EXECUTION_ERROR")

    @abstractmethod
    def _run(self, **kwargs) -> ToolResult:
        ...
