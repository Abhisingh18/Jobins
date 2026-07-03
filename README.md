# Resource-Constrained Agentic Planning Loop

A ReAct agent that solves tasks with 3 tools under a **hard budget of 10 LLM
calls and $0.20 per task**, running entirely on a **free local model
(Ollama, llama3.2:3b)** with simulated token costs so the monetary enforcer
is observably doing real work.

## Quick start (single command)

```bash
docker compose up --build agent
```

This starts Ollama, pulls `llama3.2:3b` (one-time, ~2 GB), then runs the
5-task evaluation suite. Results land in `traces/` (per-task JSON traces +
`test_results.md`).

Run a single custom task:

```bash
docker compose run agent python main.py "your task here"
```

### Running locally without Docker

```bash
pip install -r requirements.txt
ollama serve &
ollama pull llama3.2:3b
python main.py --all-tests          # or: python main.py "your task"
```

### API keys / configuration

Copy `.env.example` to `.env`. No API key is required out of the box: the LLM
is local (Ollama) and web search uses DuckDuckGo. Every setting (budget
limits, model name, mock price, and any future paid `SEARCH_API_KEY`) is
injected into the container via `env_file: .env` in `docker-compose.yml` —
edit `.env` and re-run; nothing is baked into the image.

## Architecture Overview

A single orchestrating loop (`agent/loop.py`) drives ReAct steps. Every LLM
call goes through one chokepoint — `OllamaClient.chat_json()` — which is
wrapped by the `BudgetEnforcer` (atomic check-then-record under a lock), so
the budget cannot be bypassed from anywhere in the codebase. Tools implement
a common `Tool` interface with a hard wall-clock timeout and typed error
categories. All shared data flows through an explicit `AgentState` dataclass
that doubles as the audit trail and the final report.

```
task ──> planning loop (THINK → ACT → OBSERVE → REFLECT)
              │ every LLM call            │ every tool call
              ▼                           ▼
        BudgetEnforcer ◄──────── Tool.execute() [hard timeout]
              │
              └─ BudgetExceededError ──> graceful partial report
```

## Planning Loop

I chose **ReAct** because with only 10 LLM calls per task, every call must
both reason and commit to an action — ReAct fuses the two into one structured
response, whereas plan-then-execute or Tree-of-Thought architectures spend
calls on planning artifacts that a 10-call budget cannot afford. Its biggest
weakness is myopia: ReAct decides one step at a time with no global plan, so
it can wander on multi-part tasks and burn budget on locally-reasonable but
globally-suboptimal steps. I mitigate (not eliminate) this by injecting the
remaining budget into every prompt and instructing the model to batch lookups
and finalize early.

## Schema Design

State is a typed `AgentState` dataclass: the task, a list of `StepRecord`s
(thought, action, observation, progress flag, replan flag + reason), a
scratchpad holding the last useful observation (the fallback answer if the
budget dies mid-task), and a status enum. The LLM never sees raw Python
state: each turn it receives the message history plus a fresh system prompt
with live budget numbers, and must reply with one JSON object
(`progress_check` / `thought` / `action` / `final_answer`) — Ollama's
`format: json` guarantees parseable output structurally, and a schema check
guards the field level. Tools return a typed `ToolResult` (success, data,
error, error_type) that is stringified for the LLM but kept structured in the
trace. The final report is just `AgentState` + the budget ledger serialized —
`test_results.md` is generated from it, not hand-written.

## Prompt Strategy

The system prompt enforces three behaviors. (1) **Tool use:** the response
format is a strict JSON contract; the tool catalog with exact argument hints
is embedded, and rules forbid repeating an identical call. (2) **Progress
checking:** every response must begin with a `progress_check` field assessing
the previous observation — this piggybacks LLM-side reflection onto the next
THINK call so reflection costs zero extra LLM calls; deterministic rules
(tool failure, empty results, repeated action) catch no-progress for free
before the LLM is even consulted. (3) **Budget awareness:** remaining calls
and dollars are re-injected every single turn with the instruction that a
partial answer now beats a perfect answer never; when replanning is forced,
the notice repeats the remaining budget so the model can decide to finalize
instead of exploring.

## Failure Modes

**Observed during testing:** on task 4 (adversarial "exact grains of sand"),
the model occasionally emitted a syntactically valid JSON object whose
`action` field was a *string* (`"action": "web_search"`) instead of the
required object — the loop caught it, replied with a corrective message, and
recovered, but that correction consumed one full LLM call from the budget of
ten. Small local models pay a real budget tax for schema discipline. A second
minor mode: DuckDuckGo occasionally rate-limits, which surfaces as a
`NETWORK_ERROR` tool failure and (correctly) triggers a replan, but wastes a
step on infrastructure noise rather than reasoning error.

## Future Work

The loop detector only catches *literally identical* (tool, args) repeats. A
naive-but-different paraphrase loop — searching "exact grains of sand count"
then "precise number sand grains" forever — is currently broken up only by
the prompt rules and budget pressure, not by code. With more time I would add
semantic action-similarity detection (embed the last N queries with a tiny
local embedding model and flag cosine-similar repeats) so paraphrased loops
trigger the same hard replan path as identical ones.

## Repository layout

```
main.py            # entrypoint (single task or --all-tests)
run_tests.py       # 5-task suite -> test_results.md + traces/*.json
agent/
  budget.py        # BudgetEnforcer: atomic hard limits + ledger
  llm.py           # budget-gated Ollama client (the ONLY path to the model)
  loop.py          # ReAct loop, tiered reflection, loop detector, graceful exit
  prompts.py       # system prompt + replan notice
  state.py         # AgentState / StepRecord schema
  tools/           # web_search, code_exec, calculator (+ base with timeouts)
decisions.md       # engineering trade-offs
test_results.md    # generated evaluation report (5 tasks, 2 adversarial)
```
