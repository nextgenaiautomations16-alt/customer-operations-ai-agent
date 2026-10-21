"""Turn an evaluation result into a readable Markdown report."""

from datetime import UTC, datetime
from typing import Any

FAKE_WARNING = (
    "> **WARNING: this run used a FAKE model (`{model}`).** It exercises the pipeline but says "
    "nothing about how a real language model performs. Do not quote these numbers as results."
)


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_markdown(result: dict[str, Any]) -> str:
    m = result["metrics"]
    model = result["model"]
    lines = [
        "# Evaluation report",
        "",
        f"- Generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- Model: `{model}`  |  Prompt version: `{result['prompt_version']}`",
        f"- Dataset: version {result['dataset_version']}, {result['dataset_size']} synthetic messages",
        "",
    ]
    if model.startswith("fake-"):
        lines += [FAKE_WARNING.format(model=model), ""]
    lines += [
        "## Headline metrics",
        "",
        "| Metric | Value | Scored on |",
        "|---|---|---|",
        f"| Category accuracy | {_pct(m['category_accuracy'])} | {m['category_scored']} labelled |",
        f"| Keyword-only baseline category accuracy | {_pct(m['keyword_baseline_category_accuracy'])} | same set |",
        f"| Priority accuracy (rules) | {_pct(m['priority_accuracy'])} | {m['priority_scored']} labelled |",
        f"| Escalation accuracy | {_pct(m['escalation_accuracy'])} | {m['escalation_scored']} labelled |",
        f"| Missed escalations / needless escalations | {m['missed_escalations']} / {m['needless_escalations']} | |",
        f"| Structured output valid (after retries) | {_pct(m['structured_output_validity'])} | {m['dataset_size']} |",
        f"| Valid on first attempt | {_pct(m['first_attempt_validity'])} | {m['dataset_size']} |",
        f"| Model failure rate | {_pct(m['model_failure_rate'])} | {m['dataset_size']} |",
        f"| Retrieval hit rate (expected policy in top 3) | {_pct(m['retrieval_hit_rate'])} | labelled |",
        f"| Grounded recommendation rate | {_pct(m['grounded_recommendation_rate'])} | answerable cases |",
        f"| Unsupported-claim rate | {_pct(m['unsupported_claim_rate'])} | model answers |",
        f"| Fabricated-citation rate | {_pct(m['fabricated_citation_rate'])} | model answers |",
        f"| Unsupported/vague handled safely | {_pct(m['unsupported_or_vague_handled_safely'])} | {m['unsupported_or_vague_n']} cases |",
        f"| Injection cases escalated | {_pct(m['injection_cases_escalated'])} | {m['injection_cases_n']} cases |",
        f"| Human-review rate | {_pct(m['human_review_rate'])} | {m['dataset_size']} |",
        f"| Latency mean / p50 / p95 (ms) | {m['latency_ms_mean']} / {m['latency_ms_p50']} / {m['latency_ms_p95']} | |",
        f"| Tokens (prompt / completion) | {m['prompt_tokens_total']} / {m['completion_tokens_total']} | |",
        f"| API cost (USD) | {m['api_cost_usd']} | {m['cost_note']} |",
        "",
        "## Per-category precision and recall",
        "",
        "| Category | Precision | Recall | Support |",
        "|---|---|---|---|",
    ]
    for category, values in m["per_category"].items():
        lines.append(
            f"| {category} | {_pct(values['precision'])} | {_pct(values['recall'])} | {values['support']} |"
        )
    lines += ["", "## Failure examples (first 15)", ""]
    if not result["failures"]:
        lines.append("No failures on this run.")
    for failure in result["failures"]:
        lines.append(f"- **{failure['id']}**: {'; '.join(failure['problems'])}")
        lines.append(f"  - message: \"{failure['message']}\"")
        lines.append(f"  - decision codes: {', '.join(failure['decision_codes']) or 'none'}")
    lines += [
        "",
        "## How to read this",
        "",
        "- The dataset is small and hand-written by the project author, so these numbers show "
        "direction, not statistical certainty.",
        "- Priority and escalation come from deterministic rules, so those scores mostly measure "
        "the rules, not the model.",
        "- The retrieval score threshold was tuned while looking at this same dataset, which makes "
        "retrieval numbers optimistic.",
        "- Synthetic Acme Cloud data only. No real customers, no real business results.",
        "",
    ]
    return "\n".join(lines)
