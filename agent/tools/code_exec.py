"""Python code execution tool.

Runs code in a separate interpreter process via subprocess with:
  - a hard process timeout (killed on expiry),
  - no shell involvement,
  - stdout/stderr capture with truncation.
"""
from __future__ import annotations

import subprocess
import sys

from .base import Tool, ToolResult

MAX_OUTPUT_CHARS = 2000
PROCESS_TIMEOUT = 10


class CodeExecTool(Tool):
    name = "code_exec"
    description = ("Execute a short Python snippet in an isolated process and "
                   "return its stdout. Use print() to output results.")
    args_hint = '{"code": "<python source code>"}'
    timeout_seconds = PROCESS_TIMEOUT + 5  # outer guard above the process timeout

    def _run(self, code: str = "") -> ToolResult:
        if not code or not code.strip():
            return ToolResult(success=False, error="code must be a non-empty string",
                              error_type="INPUT_ERROR")
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", code],  # -I: isolated mode
                capture_output=True,
                text=True,
                timeout=PROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(success=False,
                              error=f"code ran longer than {PROCESS_TIMEOUT}s and was killed",
                              error_type="TIMEOUT")

        stdout = (proc.stdout or "")[:MAX_OUTPUT_CHARS]
        stderr = (proc.stderr or "")[:MAX_OUTPUT_CHARS]
        if proc.returncode != 0:
            return ToolResult(success=False, error=stderr or "non-zero exit",
                              error_type="EXECUTION_ERROR")
        if not stdout.strip():
            return ToolResult(success=True,
                              data="(code ran successfully but printed nothing — "
                                   "use print() to see values)")
        return ToolResult(success=True, data=stdout)
