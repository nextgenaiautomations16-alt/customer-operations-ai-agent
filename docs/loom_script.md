# Loom script (4–5 minutes)

Record after you have run the evaluation with a real model, so every number you say is one you can show on screen. Replace the *[brackets]* with your real values. Do not say anything you cannot show.

**0:00 — Hook (20s)**
"Hi, I'm Noreen. This is a customer-support triage system I built for a fictional SaaS company, with synthetic data. The goal wasn't a chatbot. It was to show how I'd put an LLM into a business workflow safely: the AI suggests, rules decide, and a human approves anything that moves money."

**0:20 — The problem (30s)**
"Support teams spend the first minutes of every ticket reading, categorising and looking up policy, and the risky tickets, like a hacked account or a legal threat, can sit in the same queue as routine ones. I'd want to fix that without letting software issue refunds."

**0:50 — Live: the brief's scenario (60s)** *(Swagger UI or `scripts\demo.py --only brief`)*
"A customer writes: 'My invoice was charged twice, my account is still locked, I've contacted support twice.' The case is stored; I process it. The model returns structured JSON, which is validated, and it cites policy POL-BILL-001. But look at the status: *escalated*, priority *high*. That came from a deterministic rule, repeat contact, not from the model."

**1:50 — Safety (60s)**
"Two things I care about. First, a refund approval without a written note is refused, and the refusal itself is in the audit log. Second, here is a prompt-injection message telling the system to approve a $5,000 refund. [Show it.] Even if a model obeyed, it has no tool that can approve anything, the keyword rules escalate it, and approval is checked on the server."

**2:50 — Failure and audit (45s)**
"I stopped Ollama: the case becomes *processing_failed*, the error is recorded, and I can retry. Every step is an audit event with the model and prompt version, and each event includes the hash of the previous one. If I edit a row directly in the database [run tamper demo], the verifier points to the exact event. To be clear, that's detection, not immutability; I documented what it can't do."

**3:35 — Evaluation and tests (45s)**
"There's a separate evaluation: [N] labelled synthetic messages. With [model], category accuracy was [X]% against [Y]% for a keyword-only baseline, [Z]% valid structured output, p50 latency [L] seconds. The dataset is small and I wrote the labels myself, so I treat these as directional. The test suite has [N] tests and runs without Ollama."

**4:20 — Limits and close (30s)**
"It's not production-ready: auth is a placeholder key, no rate limiting, SQLite, no real customer validation. If I were deploying this for a real team, I'd start with a shadow-mode pilot and measure a baseline first. The code and docs are in the repo. Thanks for watching."

## Tips
- Keep one terminal and the browser on screen; do not scroll code.
- If something fails live, say so and show the failure handling; that is part of the story.
- State that data is synthetic and that it has not been used with real customers.
