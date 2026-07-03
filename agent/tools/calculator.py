"""Custom tool: safe calculator.

Evaluates arithmetic expressions using a whitelisted AST walk — no eval(),
no name lookups, no attribute access. Deterministic and instant, so the
agent can do math without spending an LLM call or a code_exec round-trip.
"""
from __future__ import annotations

import ast
import math
import operator

from .base import Tool, ToolResult

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {
    "sqrt": math.sqrt, "log": math.log, "log10": math.log10, "exp": math.exp,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "abs": abs,
    "round": round, "floor": math.floor, "ceil": math.ceil,
}
_CONSTS = {"pi": math.pi, "e": math.e}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_safe_eval(node.left), _safe_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in _FUNCS:
        args = [_safe_eval(a) for a in node.args]
        return _FUNCS[node.func.id](*args)
    raise ValueError(f"disallowed expression element: {ast.dump(node)[:80]}")


class CalculatorTool(Tool):
    name = "calculator"
    description = ("Evaluate an arithmetic expression exactly. Supports + - * / // % ** "
                   "parentheses, sqrt/log/exp/trig/round, and constants pi, e. "
                   "Example: '1000 * (1 + 0.05) ** 10'")
    args_hint = '{"expression": "<math expression>"}'
    timeout_seconds = 5

    def _run(self, expression: str = "") -> ToolResult:
        if not expression or not expression.strip():
            return ToolResult(success=False, error="expression must be non-empty",
                              error_type="INPUT_ERROR")
        try:
            tree = ast.parse(expression, mode="eval")
            value = _safe_eval(tree)
        except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}",
                              error_type="EXECUTION_ERROR")
        return ToolResult(success=True, data=f"{expression} = {value}")
