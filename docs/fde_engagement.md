# FDE engagement: how I would approach this with a real customer

> **Everything on this page is fictional.** "Acme Cloud" and its numbers are invented for the exercise. This is a template for how a Forward Deployed Engineer would structure the work, not a record of a real engagement.

## Fictional customer profile
Acme Cloud, a B2B SaaS company with ~40 support staff, two tiers (Starter, Pro), email and in-app chat, 09:00–17:00 UTC coverage. Tickets live in a helpdesk tool; billing in a separate billing system; policies in a wiki.

## Problem statement
Agents spend the first part of every ticket reading, categorising, looking up policy and judging urgency. Urgent or risky tickets (security, legal threats, outages, repeat contacts) can sit in the same queue as routine ones. Leadership wants faster, more consistent first triage **without** giving software the power to move money or change accounts.

## Assumptions that must be validated (not assumed true)
1. Categories and priorities in the helpdesk are used consistently enough to be a ground truth.
2. Policies in the wiki are current and are the actual source of truth for agents.
3. Agents will accept an AI suggestion if it shows its evidence, and will not just rubber-stamp it.
4. Refunds and account unlocks genuinely need a human approver (compliance may say more).
5. Ticket text can be sent to a locally hosted model (data residency, PII rules).
6. Volume and message length fit what a local model can serve.
7. A first-response-time target exists and is measured today.

## Discovery questions
- Walk me through the last 10 tickets from arrival to resolution. Where did time go?
- Which mistakes are expensive: a wrongly refunded charge, a slow security response, a wrong-queue ticket?
- Who is allowed to approve what today? Is that written down?
- What does "urgent" mean to your team? Can you show examples from the last month?
- Where do policies live, who owns them, how often do they change?
- What is the current time to first response, correct-routing rate, and manual-touch rate? How are they measured?
- What data may leave which systems? Any regulators (GDPR, SOC 2, PCI)?
- What must this integrate with (helpdesk, billing, identity)? Who owns those APIs?
- What would make you switch this off after a week?

## Functional requirements
FR1 Accept a message through an API and store it. FR2 Classify category and priority. FR3 Extract sentiment, requested resolution, prior contacts. FR4 Retrieve relevant policy text and cite it. FR5 Recommend an action grounded in cited policy, or say it cannot. FR6 Apply deterministic escalation rules. FR7 Require human approval for consequential actions. FR8 Record an audit event for every significant step, including refusals. FR9 Let a human approve, reject, escalate or resolve. FR10 Evaluate quality against a labelled dataset on demand.

## Non-functional requirements
Reliability (never a 500 because the model misbehaved; bounded retries and timeouts) · Safety (AI cannot execute actions) · Traceability (who/what/when/which model and prompt) · Privacy (no message text in logs; synthetic data only here) · Reproducibility (one-command setup and evaluation) · Cost (no paid APIs in the MVP) · Explainability (decision codes and cited sources on every case).

## Workflow
See the diagram in `README.md` / `docs/design.md`.

## Architecture decisions and trade-offs
See `docs/design.md` ("Decisions and trade-offs").

## Risks and mitigations
| Risk | Mitigation in this project | Remaining gap |
|---|---|---|
| Model invents policy | Must cite retrieved IDs; invented IDs and uncited claims escalate | Model can still *paraphrase* a real source wrongly; needs human review sampling |
| Prompt injection | Delimited untrusted input, no tools, keyword escalation, server-side approval | Novel phrasing can evade keywords |
| Over-trust ("automation bias") | Every case still goes to a person; evidence shown; refunds need a written note | Needs UX research with real agents |
| Model unavailable | `processing_failed` + retry; risky keywords still escalate | No queueing/alerting yet |
| Wrong priority rules | Rules are explicit and editable; evaluated against labels | Rules written by me, not by Acme's team |
| Data leakage | Local model; no message text in logs/audit | No redaction layer |
| Metric gaming | Report failures and limitations with every run | Requires discipline from owners |

## Acceptance criteria
See `docs/design.md`.

## Pilot rollout plan (proposal)
1. **Weeks 0–2, shadow mode:** run on live tickets copied read-only; agents never see output. Compare AI category/priority with agents' final labels. Fix rules and prompts; re-run the evaluation on the same dataset after each change.
2. **Weeks 3–4, assist mode, one queue (e.g. general questions):** show suggestions to a small group of agents; they accept/edit/reject with one click. Track acceptance and edit rate.
3. **Weeks 5–6, extend to billing with approvals:** keep every refund behind a named approver. Sample-audit 10% of accepted suggestions.
4. **Decision gate:** expand, hold, or stop based on the metrics below and agent feedback. **No automatic actions** are enabled in this pilot.

## Customer feedback loop
Weekly 30-minute review with 2–3 agents and the support lead: top-5 wrong suggestions, top-5 escalations that were unnecessary, missing policies. Every correction becomes a new labelled example; a change to rules, prompt or model is accepted only if the evaluation on the full dataset does not get worse. Keep a change log (prompt version is already stored with each AI run).

## Business metrics to track
| Metric | How measured | Baseline needed |
|---|---|---|
| Time to first response | Helpdesk timestamps | Yes, measure for 2+ weeks **before** the pilot |
| Correct routing rate | Agent re-routing events | Yes |
| Manual review rate | Share of cases needing human triage work | Yes |
| Escalation precision/recall | Compared with expert labels | Build the labelled set |
| Resolution time | Ticket open to resolved | Yes |
| Suggestion acceptance / edit rate | Pilot UI | n/a |

**No cost or speed improvement should be claimed without a documented baseline and a fair comparison.** This repository contains no such claim, because it has no real customer data.
