"""Web search tool backed by DuckDuckGo (no API key required).

Uses the `ddgs` package. Network timeout is enforced at two levels:
per-request inside ddgs and a hard wall-clock timeout in Tool.execute().
"""
from __future__ import annotations

from .base import Tool, ToolResult

MAX_RESULTS = 5


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for current information. Returns top result snippets."
    args_hint = '{"query": "<search terms>"}'
    timeout_seconds = 20

    def _run(self, query: str = "") -> ToolResult:
        if not query or not query.strip():
            return ToolResult(success=False, error="query must be a non-empty string",
                              error_type="INPUT_ERROR")
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # older package name fallback

        try:
            with DDGS(timeout=10) as ddgs:
                results = list(ddgs.text(query, max_results=MAX_RESULTS))
        except Exception as exc:
            return ToolResult(success=False, error=f"search failed: {exc}",
                              error_type="NETWORK_ERROR")

        if not results:
            return ToolResult(success=True, data="No results found for this query.")

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            body = (r.get("body", "") or "")[:300]
            lines.append(f"[{i}] {title}\n    {body}")
        return ToolResult(success=True, data="\n".join(lines))
