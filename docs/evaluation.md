# Evaluation

## What is measured
Every message in `data/synthetic_cases.json` goes through the same `run_pipeline` the API uses. Results are compared with the hand-written labels.

| Metric | Meaning |
|---|---|
| Category accuracy | Model's category vs label, on items that have a category label. A **keyword-only baseline** is reported next to it so you can see whether the model adds anything |
| Per-category precision / recall | One row per category |
| Priority accuracy | Final priority (from the **rules**) vs label |
| Escalation accuracy, missed / needless escalations | Whether the case ended as `escalated` when it should (and the two error types separately) |
| Structured output validity | Share of messages where a valid answer was obtained (after retries). First-attempt validity is reported too |
| Model failure rate | Share where no valid answer could be obtained |
| Retrieval hit rate | An expected policy appears in the top 3 passages |
| Grounded recommendation rate | Among answerable messages, the recommendation cites at least one retrieved source |
| Unsupported-claim rate | Model answers that cite an invented source, or make a substantive recommendation with no valid citation |
| Unsupported / vague handled safely | For unsupported or too-vague messages, the case was not given a confident policy answer, refund or unlock without escalation |
| Injection cases escalated | Messages containing override attempts all reached a human |
| Human-review rate | Share of cases that are **not** automation candidates (today almost always 100%, by design) |
| Latency mean / p50 / p95 | End-to-end per message, including retrieval and retries |
| Tokens, API cost | Tokens come from Ollama. API cost is 0 because no paid API is used; **local compute (CPU/GPU time, electricity) is not measured** |

A label of `null` means "genuinely ambiguous, not scored for that field."

## Dataset
45 synthetic messages (version `1.0`). Counts by tag (a message can have several tags): normal 19, escalation 8, ambiguous 8, conflicting 5, missing information 4, out of scope 3, prompt injection 3, unsupported (no policy exists) 2, plus security, legal, outage, repeat-contact and multi-issue cases. Each item has a category, priority, whether it should escalate, expected policy sources, tags and notes.

## How to run (PowerShell)
```powershell
python scripts\run_eval.py --backend ollama --model qwen2.5:7b
python scripts\run_eval.py --backend ollama --model llama3.2:3b --label baseline
```
On CPU a 7B model can take 10–60 seconds per message, so a full run can take 10–40 minutes. Use `--limit 5` for a quick trial.

## Rules for honest reporting
1. **Record a baseline first** (model, prompt version, dataset version) before changing anything.
2. Change one thing at a time (prompt version, model, retrieval threshold, a rule) and re-run on the **same** dataset.
3. Keep the `.json` and `.md` reports from every run in `reports/`.
4. Never present results from `fake-*` models as model quality. Reports from fake models carry a warning banner.
5. Always quote the dataset size and list known limitations next to any number.

## Caveats you must state when quoting numbers
- 45 messages, written and labelled by one person: small, and not independent.
- The retrieval score threshold (3.0) was chosen while looking at this dataset, so retrieval numbers are optimistic.
- Priority and escalation scores mostly measure the deterministic rules, not the model.
- Local model results depend on hardware, Ollama version and model build.

## Results log (fill this in from real runs)
| Date | Model | Prompt | Dataset | Category acc. | Escalation acc. | Valid output | Failure rate | p50 latency | Report file |
|---|---|---|---|---|---|---|---|---|---|
| *(not yet run with a real model)* | | | | | | | | | |

## What the pipeline-only smoke test showed (not a model result)
With the rule-based `heuristic` fake, the pipeline processed all 45 messages without errors and every prompt-injection message ended up escalated. Four items were wrong, and each exposes a known weak spot rather than a model flaw: **E06** (an unrecognised charge: billing or security?), **A08** (a legal-advice question that the keyword word "renewal" pulls into billing), **A09** (a custom-price contract request whose priority the keyword rules over-rate) and **M01** ("My invoice is wrong." matched no policy above the retrieval threshold, so confidence was low and it escalated). These numbers say **nothing** about a real language model, and the labels were not changed to make them look better.
