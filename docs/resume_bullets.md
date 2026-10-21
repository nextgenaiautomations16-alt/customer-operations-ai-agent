# Resume bullets (only what is true and checkable)

Use the **verified now** group as written. Use the **after you run it** group only once you have real numbers; fill in brackets from `reports\latest.md` and delete any bullet whose numbers you do not have. Label the project honestly as a personal project with synthetic data.

## Project line
**Customer Operations AI Agent** — personal project (synthetic data) · Python, FastAPI, Pydantic, SQLite, Ollama, pytest

## Verified now (true of the code)
- Built a FastAPI service that triages synthetic support tickets using a local LLM (Ollama): retrieves cited policy passages, validates structured JSON output with Pydantic, and applies deterministic rules for priority and escalation.
- Designed human-in-the-loop controls enforced server-side: the AI can only recommend, while approval, rejection and resolution are separate human endpoints with a required note for consequential actions.
- Implemented a hash-chained, append-only application audit log with a verification endpoint, and tests showing that edited or deleted events are detected; documented its limits (not tamper-proof).
- Hardened the LLM integration: bounded retries and timeouts, graceful fallback when the model is unavailable or returns malformed output, citation checking against retrieved sources, and prompt-injection handling (delimited input, no model tools, independent escalation rules).
- Wrote an automated test suite (**[run `pytest` and put your own count here]** tests with deterministic fake models, no Ollama required) covering state transitions, idempotency, failure paths, audit tamper detection and a simulated concurrent-processing race.
- Built a reproducible evaluation pipeline and a 45-message labelled synthetic dataset covering normal, ambiguous, conflicting, unsupported and prompt-injection cases; the pipeline runs the same code path as the API.
- Wrote FDE-style engagement documentation: discovery questions, assumptions, risks, acceptance criteria, shadow-mode pilot plan and a customer feedback loop.

## After you run it (fill in or delete)
- Evaluated [model] on [45] hand-labelled synthetic messages: [X%] category accuracy versus [Y%] for a keyword-only baseline, [Z%] valid structured output, p50 latency [L] s on [hardware]; documented failure cases and limitations.
- Compared [model A] and [model B] on the same dataset and prompt version, recording [metric differences].

## Do not write
- Anything about savings, hours saved, response-time improvement, customers or revenue. There is no real customer data behind this project.
- "Production-ready", "deployed", or "enterprise" unless that becomes true.
- Numbers you did not measure.
