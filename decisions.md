# Engineering Decisions

- I considered **charging simulated cost only for completed LLM calls** but
  chose **to also charge a call slot for timed-out/failed calls** because a
  timeout still consumed real wall-clock and compute resources, and an agent
  that could retry failures for free would have an effectively unlimited call
  budget under a flaky model server.

- I considered **a separate LLM call for reflection after every tool call**
  but chose **tiered reflection (deterministic rules first, LLM reflection
  piggybacked as a mandatory `progress_check` field on the next THINK call)**
  because with a 10-call budget, dedicated reflection calls would consume up
  to half the budget on meta-reasoning; rules catch the common failure cases
  (errors, empty results, identical repeats) for zero calls.

- I considered **llama3.1:8b for stronger reasoning** but chose
  **llama3.2:3b** because the target machine is CPU-only with 7.7 GB RAM — an
  8B model would swap and make each of the 10 calls take minutes, and a
  smaller model that answers in seconds exercises the budget/replanning
  machinery far better than a smarter model that times out.

- I considered **DuckDuckGo HTML scraping or a paid search API (Tavily)** but
  chose **the `ddgs` library** because it needs no API key (single-command
  reproducibility for evaluators) while still exercising real network
  failure modes (timeouts, rate limits) that the tool error taxonomy and
  replanning path must handle.

- I considered **mapping the `^` (XOR) AST node to `pow` in the calculator**
  but chose **textually rewriting `^` to `**` before parsing** because the
  AST mapping keeps XOR's precedence (looser than `*`) and silently computed
  `1000*(1.05)^10` as `(1000*1.05)**10` — a wrong-answer bug observed live in
  testing — while the textual rewrite gives `^` the power precedence every
  real calculator uses.

- I considered **killing execution with `sys.exit()` when the budget is hit**
  but chose **raising a typed `BudgetExceededError` caught only at the
  orchestrator level** because the agent must report exactly what it
  completed — an exception carries the budget snapshot up to the reporting
  layer, while `sys.exit()` would discard the partial state the assignment
  explicitly asks for.
