from .base import Tool, ToolResult
from .calculator import CalculatorTool
from .code_exec import CodeExecTool
from .web_search import WebSearchTool

TOOLS: dict[str, Tool] = {
    t.name: t for t in (WebSearchTool(), CodeExecTool(), CalculatorTool())
}


def tool_catalog() -> str:
    """Human/LLM readable list of tools for the system prompt."""
    lines = []
    for t in TOOLS.values():
        lines.append(f"- {t.name}: {t.description} args: {t.args_hint}")
    return "\n".join(lines)
