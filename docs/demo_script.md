# Demo script (about 10 minutes)

All data is synthetic. Use `LLM_BACKEND=ollama` for the real thing, or `heuristic` for an offline dry run (say so out loud if you use it).

## Setup (before recording)
```powershell
.\.venv\Scripts\Activate.ps1
Remove-Item data\app.db -ErrorAction SilentlyContinue     # clean slate
uvicorn app.main:create_app --factory                      # terminal 1
```
Terminal 2 for scripts. Browser on <http://127.0.0.1:8000/docs> with **Authorize** done.

## Run order

| # | Show | How | What to point out |
|---|---|---|---|
| 1 | Health | `GET /health?deep=true` | Database ok, 37 policy passages loaded, model reachable |
| 2 | **Normal case** | `python scripts\demo.py --api-key <key> --only normal` | Cited source, `pending_review`, low priority, an automation *candidate* but still reviewed by a person |
| 3 | **The brief's scenario** | `--only brief` | "Charged twice, locked, contacted twice": high priority, `E_REPEAT_CONTACT`, escalated; the rules, not the AI, decided |
| 4 | **Uncertain case** | `--only vague` or `--only unsupported` | Not enough information or no policy: the system asks for more info or escalates instead of inventing a policy |
| 5 | **Human approval** | `--only refund` | Approve without a note is refused (422); with a note works; resolve; the AI never approved anything |
| 6 | **Server-side enforcement** | end of the demo run | Approving an unprocessed case returns 409 and the refusal is in the audit log |
| 7 | **Prompt injection** | `--only injection` | Escalated with `E_INJECTION_SUSPECTED`; even a model that obeys cannot approve |
| 8 | **Model failure** | Stop Ollama (tray icon, Quit) or restart the server with `LLM_BACKEND=unavailable`, then `--only normal` | `processing_failed`, error category recorded, no crash; restart Ollama and call `/process` again to retry |
| 9 | **Audit trail** | `GET /cases/{id}/audit` | Actor (system / ai / human), model, prompt version, hashes, no message text |
| 10 | **Audit integrity** | `python scripts\tamper_demo.py --api-key <key>` | Edit one row directly in SQLite, `/audit/verify` flags the exact event; value restored afterwards. Say plainly: this is *detection*, not immutability |
| 11 | **Automated tests** | `pytest` | 139 tests, no Ollama needed (state the real number you see on your machine) |
| 12 | **Evaluation** | open `reports\latest.md` | Real metrics, dataset size, failure examples and limitations. If you have not run it with a real model, do not show numbers |

## Failure-case checklist (have these ready)
- Ollama stopped → expect `processing_failed`.
- Wrong or missing key → 401 / 503 with the standard error body.
- Same `Idempotency-Key` twice → 201 then 200 with the same case id.
