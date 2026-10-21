# Case study: a triage system where AI suggests, rules decide, and humans approve

*A personal portfolio project built on synthetic data for a fictional company. No real customer, no real business results. Items in [brackets] are for you to fill in from your own runs; leave out anything you did not measure.*

## The problem
Support teams read, categorise and look up policy for every ticket, and risky tickets (a hacked account, a legal threat, an outage) wait in the same queue as routine ones. A naive "LLM answers the ticket" fails in the ways that matter here: it can invent policy, follow instructions hidden in a customer's message, or promise a refund.

## Constraints I set
$0 budget (local model through Ollama), no paid APIs, synthetic data only, finishable as an MVP, and every claim must be measurable.

## What I built
A FastAPI service that: validates and stores a case; retrieves relevant policy passages; asks a local LLM for a schema-validated recommendation with citations; applies deterministic rules for priority and escalation; requires a human to approve consequential actions; and records every step in a hash-chained audit log. A separate evaluation pipeline runs a labelled dataset through the same code path.

## Key design decisions (and why)
1. **The model has no power.** It returns JSON with one of six recommended actions. Approval, refund and resolution exist only behind human endpoints that the server checks. This makes prompt injection a lower-stakes problem: there is nothing dangerous to obey.
2. **Rules own priority and escalation.** They are explainable and unaffected by model drift. The model's own "urgency" is advisory.
3. **Trust nothing the model says.** Output is parsed and validated; retries are bounded; cited sources must be among the passages actually retrieved; invented citations escalate.
4. **Fail toward a human.** Model down, bad JSON, no supporting policy, low confidence, or risky keywords all lead to a person, never to a confident wrong answer.
5. **Evaluate the real path.** The evaluation calls the same pipeline function as the API.
6. **Plain `sqlite3`** for five tables: simplest to read and test, with a documented PostgreSQL path.

## How I tested it
139 automated tests with deterministic fake models, so they run without Ollama or internet: rules and state transitions, approval enforcement, audit tamper detection, malformed and unavailable model responses, retries, fabricated citations, missing knowledge, prompt-injection handling, duplicate requests, a simulated concurrent-processing race, and evaluation metrics against a hand-calculated mini dataset. The test run found a real bug in my metrics code (a database connection used after it was closed), which I fixed. [HTTP-layer tests: report your own result from running `pytest`.]

## Results
*Fill from `reports\latest.md` after a real-model run. If you have not run one, say "evaluation pipeline built; real-model baseline in progress."*
- Dataset: [45] synthetic messages, hand-labelled by me
- Model / prompt: [qwen2.5:7b / v1]
- Category accuracy: [X%] (keyword-only baseline: [Y%])
- Escalation accuracy: [X%]; missed escalations: [n]
- Valid structured output: [X%]; model failure rate: [X%]
- Grounded recommendation rate: [X%]; unsupported-claim rate: [X%]
- Latency p50 / p95: [a s / b s] on [your hardware]
- Three failures I found and what they taught me: [E06 / A08 / M01 style examples from your report]

## What I learned
- Whether the model adds value must be shown against a no-AI baseline; I report one.
- Safety properties are better implemented as *architecture* (no tools, server-side checks) than as prompt wording.
- A small test caught a bug a code read-through missed.
- [Add one thing the real evaluation taught you.]

## Limitations (stated up front)
Small self-labelled dataset; retrieval threshold tuned on the same data; keyword rules are blunt; single-process SQLite; shared-key placeholder authentication; never validated with a real support team or real tickets. See `docs/security.md`.

## If this were a real engagement
Run shadow mode against live tickets with a measured baseline first, add real auth and PII handling, integrate with the helpdesk and billing systems, and review wrong suggestions weekly with agents. See `docs/fde_engagement.md`.
