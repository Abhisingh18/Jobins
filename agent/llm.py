"""Budget-gated Ollama client.

This module is the ONLY way the agent talks to a model. Every call:
  1. prechecks the budget (refuses to start if calls are spent),
  2. runs the request with a hard timeout,
  3. charges real token counts against the simulated cost budget.
"""
from __future__ import annotations

import json
import os

import requests

from .budget import BudgetEnforcer

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
LLM_TIMEOUT_SECONDS = int(os.environ.get("LLM_TIMEOUT_SECONDS", "180"))


class LLMError(Exception):
    """Model/server failure (not a budget failure)."""


class OllamaClient:
    def __init__(self, budget: BudgetEnforcer, model: str = OLLAMA_MODEL,
                 host: str = OLLAMA_HOST):
        self.budget = budget
        self.model = model
        self.host = host

    def chat_json(self, messages: list[dict], meta: str = "") -> dict:
        """One chat call that must return a JSON object.

        Counts as exactly one LLM call regardless of outcome. Token cost is
        simulated from Ollama's real prompt+completion token counts.
        """
        self.budget.precheck_llm_call()
        try:
            resp = requests.post(
                f"{self.host}/api/chat",
                json={
                    "model": self.model,
                    "messages": messages,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 400},
                },
                timeout=LLM_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.Timeout as exc:
            # A timed-out call still consumed a call slot: charge a nominal cost.
            self.budget.charge_llm_call(tokens=0, meta=f"timeout:{meta}")
            raise LLMError(f"LLM call timed out after {LLM_TIMEOUT_SECONDS}s") from exc
        except requests.exceptions.RequestException as exc:
            self.budget.charge_llm_call(tokens=0, meta=f"error:{meta}")
            raise LLMError(f"LLM request failed: {exc}") from exc

        tokens = data.get("prompt_eval_count", 0) + data.get("eval_count", 0)
        self.budget.charge_llm_call(tokens=tokens, meta=meta)

        content = data.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"LLM returned malformed JSON: {content[:200]!r}") from exc
