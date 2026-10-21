# Security, integrity and production gaps

## What is implemented
- Input limits and schema validation on every request; consistent error envelope that never leaks stack traces.
- Parameterised SQL everywhere (no string-built queries from user input; only fixed column names are interpolated).
- Customer text is isolated from instructions in the prompt, delimiter look-alikes are stripped, and keyword rules escalate injection attempts independently of the model.
- The model has **no tools**: its output is parsed JSON with six allowed actions. It cannot run SQL, shell commands, payments, refunds or account changes.
- Server-side workflow enforcement; only human endpoints can set `approved`, `rejected`, `resolved`.
- Audit log is write-once at the application level and hash-chained; refused operations are logged too.
- Logs are structured JSON and never contain customer message text; audit events store hashes and lengths only. Model chain-of-thought is not requested or stored.
- Secrets come from environment variables / `.env` (git-ignored); `.env.example` contains no real values.
- Synthetic data only.

## What the audit hash chain proves, and what it does not
**Proves:** if an event in the *middle* of the log is edited, deleted, inserted or reordered, `/audit/verify` reports the first broken event. (Tested.)

**Does not prove:**
- Someone with write access to the SQLite file can rewrite the *entire* chain consistently. The log is **not tamper-proof or immutable.**
- Deleting events from the *end* of the log leaves a valid shorter chain. (A test documents this.) To detect it, record `head_hash` from `/audit/verify` somewhere outside the database (a ticket, email, CI log, write-once storage) and compare later.
- It says nothing about whether the recorded events were *correct*, only that they were not changed afterwards.

Stronger options for real use: append-only/WORM storage, a database role that can only INSERT, periodic signed checkpoints, shipping events to an external log service.

## Known gaps for any real or public deployment
| Gap | Why it matters |
|---|---|
| **Authentication is one shared key** | No per-user identity; the `reviewer` field is free text. Need SSO/OIDC, roles (agent, lead, auditor), and the reviewer taken from the token, not the request body |
| **`POST /cases` is unauthenticated** | Anyone can create cases. Needs rate limiting, CAPTCHA or signed intake, size quotas |
| **No rate limiting** | `/process` triggers expensive model calls; trivially abusable |
| **No TLS** | Terminate TLS at a reverse proxy; never expose uvicorn directly |
| **Case content returned to the submitter** | `POST /cases` echoes the stored message and ID; real systems would return only an opaque receipt |
| **PII** | Real tickets contain personal data. Needs redaction before the model and storage, retention limits, deletion on request, access logging |
| **Keyword safety rules** | Evadable by unusual phrasing; defence in depth, not a guarantee against prompt injection |
| **Model and prompt change control** | Changing model or prompt should require a re-run of the evaluation on the same dataset and a recorded comparison |
| **Backups, migrations, monitoring** | None implemented |
| **Concurrency at scale** | SQLite, single process; not load-tested |
| **Dependency and supply-chain hygiene** | Pin and scan dependencies before real use |

## Reporting
This is a portfolio project. If you find a security problem in it, open an issue.
