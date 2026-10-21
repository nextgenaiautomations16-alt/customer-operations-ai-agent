# Interview preparation

Answers below describe how this project works. Adjust numbers to your own runs, and say "I haven't measured that" when you haven't.

## Technical questions

**Walk me through the architecture.**
Requests hit a FastAPI layer that validates input and returns a consistent error envelope. A service layer runs a pipeline: keyword signal detection, BM25 policy retrieval, an LLM call through Ollama that must return schema-validated JSON, then a deterministic rules step that sets priority and next status. Everything is saved to SQLite in one transaction together with hash-chained audit events. Humans approve or reject through separate endpoints.

**Why not let the LLM decide priority and escalation?**
Those decisions need to be explainable, consistent and resistant to prompt injection. Rules give decision codes I can audit and test. The model's urgency guess is advisory. The model is good at reading messy text; rules are good at policy.

**How do you handle prompt injection?**
Defence in depth. Customer text is delimited and treated as data, with tag look-alikes stripped. The model has no tools; it only emits one of six recommendation labels. Independent keyword rules escalate override attempts. And approval is enforced server-side, so even a fully compromised model output cannot approve or resolve anything. I have tests where the fake model *obeys* the attack and the case still ends escalated. I would not claim this is injection-proof: novel phrasing can evade keywords.

**What if the model returns invalid JSON, times out, or is down?**
Output is parsed and validated with Pydantic. Invalid output and transient errors get bounded retries (the retry message asks for JSON only); an unavailable model is not retried. If it still fails, the case becomes `processing_failed` and is retryable, the failure is audited with an error category, and if the message has risk keywords (security, legal, outage) it escalates to a human anyway. There are tests for each path.

**How do you stop it inventing policy?**
The prompt allows only retrieved passages, and the code checks that every cited ID was actually retrieved. Invented IDs, or a substantive recommendation with no valid citation, escalate. If retrieval finds nothing above the score threshold, the model is told there are no passages and the system asks for more information or escalates. Caveat: a model can still misstate a real policy, which is why humans review.

**Explain the audit log. Is it tamper-proof?**
No. Each event stores the previous event's hash and its own SHA-256 over every field. Editing, deleting or reordering a middle event breaks the chain, and `/audit/verify` reports which one (tested). But someone with database write access could rewrite the whole chain, and truncating the tail is not detectable from inside the database; a test documents that. To detect it you record the head hash externally, or use append-only storage.

**How do you make writes safe?**
Idempotency keys on case creation (same key and body returns the same case, different body is a 409). State changes and their audit events share one `BEGIN IMMEDIATE` transaction. The LLM call happens outside any transaction so it doesn't hold a lock, and the status is re-checked with a conditional `UPDATE` when saving, so two simultaneous `/process` calls can't both win. A test simulates that race.

**Why plain sqlite3 and not SQLAlchemy?**
Five tables; plain SQL is easy to read and I could test it directly with no extra dependencies. The trade-off is a PostgreSQL move means rewriting queries or adopting SQLAlchemy then. I wouldn't claim it scales; it's single-process.

**Why BM25 instead of embeddings?**
Start with the simplest thing that can be measured. The evaluation reports a retrieval hit rate; if misses justify it, embeddings are next. (I already have `nomic-embed-text` locally.) Known weakness: vocabulary mismatch, partly covered by a small synonym table.

**How do you evaluate an AI feature?**
A labelled dataset covering normal, ambiguous, missing-information, conflicting, unsupported and injection cases; the same code path as production; and metrics for accuracy (against a no-AI baseline), output validity, grounding, failure rate and latency. I record a baseline, change one thing at a time and re-run on the same dataset. My dataset is small and self-labelled, so I treat results as directional.

**What would you do first to take this to production?**
Real authentication and per-user identity for approvers, rate limiting on intake, PII redaction and retention rules, an external anchor for the audit head hash, monitoring and alerts, and a pilot in shadow mode with a measured baseline before anything is shown to agents.

## FDE / behavioural questions

**Describe how you'd run a customer discovery.**
Start from the last ten real tickets and trace where time goes; ask which mistakes are expensive; who may approve what; where policies live and who owns them; what data may leave which systems; what they measure today. List assumptions to validate rather than treating them as facts (`docs/fde_engagement.md`).

**How would you roll this out?**
Shadow mode first (no agent sees output), then assist mode in one low-risk queue, then billing with named approvers, with a decision gate based on measured metrics and agent feedback. No automatic actions in the pilot.

**How do you explain this to a non-technical stakeholder?**
"It reads each message, finds the relevant company policy, and suggests what to do and why, with sources. Fixed rules decide how urgent it is and when a person must take over. It can't issue refunds or change accounts; a named person approves those, and everything is logged."

**What would you claim, and not claim?**
I'd claim: it runs end to end on synthetic data; these tests pass; these evaluation numbers on this dataset. I wouldn't claim: production-ready, cost or time savings, or any result from a real customer. I have none.

**Tell me about a bug you found.**
My metrics endpoint ran a query after its database connection was closed. My integration test for metrics failed with "Cannot operate on a closed database"; I moved the queries inside the connection block. A code read-through hadn't caught it.

**What would you do differently with more time?**
Validate rules and labels with a real support team, add embeddings if retrieval misses justify it, move approvals to real authentication, and add a dashboard.
