"""Reproducible evaluation: run every labelled message through the SAME pipeline the API uses.

Nothing here is invented. Every number comes from running the dataset and comparing the
result with the hand-written labels. A label of ``null`` means "not scored for that field".
"""

import json
import statistics
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.ai.client import LLMClient
from app.core.enums import Action, CaseStatus, Category
from app.core.signals import detect_signals, keyword_category
from app.retrieval.retriever import Retriever
from app.services.pipeline import PipelineConfig, PipelineResult, run_pipeline

RISKY_ACTIONS = {Action.REPLY_WITH_POLICY_INFO, Action.REFUND_REVIEW, Action.ACCOUNT_UNLOCK_REVIEW}
SAFE_TAGS = {"unsupported", "missing_info"}


def load_dataset(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    ids = [item["id"] for item in data["items"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Dataset contains duplicate ids")
    return data


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _percentile(values: list[int], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return float(ordered[index])


def evaluate_item(
    item: dict[str, Any], result: PipelineResult
) -> dict[str, Any]:
    outcome, decision = result.outcome, result.decision
    analysis = outcome.analysis
    predicted_category = analysis.category.value if analysis else None
    return {
        "id": item["id"],
        "tags": item.get("tags", []),
        "model_ok": outcome.ok,
        "first_attempt_valid": outcome.first_attempt_valid,
        "attempts": outcome.attempts,
        "error_category": outcome.error_category,
        "predicted_category": predicted_category,
        "keyword_category": keyword_category(item["message"], detect_signals(item["message"])).value,
        "predicted_priority": decision.priority.value,
        "predicted_escalate": decision.status == CaseStatus.ESCALATED,
        "status": decision.status.value,
        "decision_codes": list(decision.reasons),
        "action": analysis.recommended_action.value if analysis else None,
        "grounded": outcome.grounded,
        "unsupported_claim": outcome.unsupported_claim,
        "fabricated_citation": bool(outcome.invalid_citations),
        "retrieved": [p.source_id for p in result.passages],
        "automation_candidate": decision.automation_candidate,
        "latency_ms": result.total_ms,
        "llm_latency_ms": outcome.latency_ms,
        "prompt_tokens": outcome.prompt_tokens,
        "completion_tokens": outcome.completion_tokens,
    }


def compute_metrics(items: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare per-item results with labels and return the headline numbers."""
    by_id = {item["id"]: item for item in items}
    total = len(rows)

    # --- Category (only where a label exists and the model produced an answer) ----------
    cat_scored = [r for r in rows if by_id[r["id"]]["expected_category"] is not None]
    cat_answered = [r for r in cat_scored if r["predicted_category"] is not None]
    cat_correct = sum(
        r["predicted_category"] == by_id[r["id"]]["expected_category"] for r in cat_answered
    )
    kw_correct = sum(
        r["keyword_category"] == by_id[r["id"]]["expected_category"] for r in cat_scored
    )
    per_category: dict[str, dict[str, float | None]] = {}
    for cat in (c.value for c in Category):
        tp = sum(
            1 for r in cat_answered
            if r["predicted_category"] == cat and by_id[r["id"]]["expected_category"] == cat
        )
        predicted = sum(1 for r in cat_answered if r["predicted_category"] == cat)
        actual = sum(1 for r in cat_scored if by_id[r["id"]]["expected_category"] == cat)
        per_category[cat] = {
            "precision": _rate(tp, predicted),
            "recall": _rate(tp, actual),
            "support": actual,
        }

    # --- Priority and escalation ---------------------------------------------------------
    pri_scored = [r for r in rows if by_id[r["id"]]["expected_priority"] is not None]
    pri_correct = sum(r["predicted_priority"] == by_id[r["id"]]["expected_priority"] for r in pri_scored)
    esc_scored = [r for r in rows if by_id[r["id"]]["expected_escalate"] is not None]
    esc_correct = sum(r["predicted_escalate"] == by_id[r["id"]]["expected_escalate"] for r in esc_scored)
    missed_escalations = sum(
        1 for r in esc_scored if by_id[r["id"]]["expected_escalate"] and not r["predicted_escalate"]
    )
    needless_escalations = sum(
        1 for r in esc_scored if not by_id[r["id"]]["expected_escalate"] and r["predicted_escalate"]
    )

    # --- Model output quality ---------------------------------------------------------------
    ok_rows = [r for r in rows if r["model_ok"]]
    answerable = [r for r in ok_rows if by_id[r["id"]]["expected_sources"]]
    retrieval_hits = sum(
        1 for r in rows
        if by_id[r["id"]]["expected_sources"]
        and set(by_id[r["id"]]["expected_sources"]) & set(r["retrieved"])
    )
    retrieval_scored = sum(1 for r in rows if by_id[r["id"]]["expected_sources"])
    grounded_answerable = sum(1 for r in answerable if r["grounded"])

    safe_rows = [
        r for r in ok_rows
        if set(r["tags"]) & SAFE_TAGS and not by_id[r["id"]]["expected_sources"]
    ]
    safe_ok = sum(
        1 for r in safe_rows if r["action"] not in {a.value for a in RISKY_ACTIONS} or r["predicted_escalate"]
    )
    injection_rows = [r for r in rows if "injection" in r["tags"]]
    injection_escalated = sum(1 for r in injection_rows if r["predicted_escalate"])

    latencies = [r["latency_ms"] for r in rows]
    review_needed = sum(1 for r in rows if not r["automation_candidate"])

    return {
        "dataset_size": total,
        "category_scored": len(cat_scored),
        "category_accuracy": _rate(cat_correct, len(cat_scored)),
        "keyword_baseline_category_accuracy": _rate(kw_correct, len(cat_scored)),
        "per_category": per_category,
        "priority_scored": len(pri_scored),
        "priority_accuracy": _rate(pri_correct, len(pri_scored)),
        "escalation_scored": len(esc_scored),
        "escalation_accuracy": _rate(esc_correct, len(esc_scored)),
        "missed_escalations": missed_escalations,
        "needless_escalations": needless_escalations,
        "structured_output_validity": _rate(len(ok_rows), total),
        "first_attempt_validity": _rate(sum(r["first_attempt_valid"] for r in rows), total),
        "model_failure_rate": _rate(total - len(ok_rows), total),
        "retrieval_hit_rate": _rate(retrieval_hits, retrieval_scored),
        "grounded_recommendation_rate": _rate(grounded_answerable, len(answerable)),
        "unsupported_claim_rate": _rate(sum(r["unsupported_claim"] for r in ok_rows), len(ok_rows)),
        "fabricated_citation_rate": _rate(sum(r["fabricated_citation"] for r in ok_rows), len(ok_rows)),
        "unsupported_or_vague_handled_safely": _rate(safe_ok, len(safe_rows)),
        "unsupported_or_vague_n": len(safe_rows),
        "injection_cases_escalated": _rate(injection_escalated, len(injection_rows)),
        "injection_cases_n": len(injection_rows),
        "human_review_rate": _rate(review_needed, total),
        "automation_candidate_rate": _rate(total - review_needed, total),
        "latency_ms_mean": round(statistics.mean(latencies), 1) if latencies else None,
        "latency_ms_p50": _percentile(latencies, 0.5),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "prompt_tokens_total": sum(r["prompt_tokens"] for r in rows),
        "completion_tokens_total": sum(r["completion_tokens"] for r in rows),
        "api_cost_usd": 0.0,
        "cost_note": (
            "No paid API is used, so API cost is 0. Local compute (CPU/GPU time, electricity) "
            "is not measured; latency is the best available proxy."
        ),
    }


def collect_failures(
    items: list[dict[str, Any]], rows: list[dict[str, Any]], limit: int = 15
) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in items}
    failures: list[dict[str, Any]] = []
    for row in rows:
        item = by_id[row["id"]]
        problems: list[str] = []
        if not row["model_ok"]:
            problems.append(f"model failure ({row['error_category']})")
        if item["expected_category"] is not None and row["predicted_category"] != item["expected_category"]:
            problems.append(f"category expected {item['expected_category']}, got {row['predicted_category']}")
        if item["expected_priority"] is not None and row["predicted_priority"] != item["expected_priority"]:
            problems.append(f"priority expected {item['expected_priority']}, got {row['predicted_priority']}")
        if item["expected_escalate"] is not None and row["predicted_escalate"] != item["expected_escalate"]:
            problems.append(f"escalate expected {item['expected_escalate']}, got {row['predicted_escalate']}")
        if row["unsupported_claim"]:
            problems.append("unsupported claim (missing or invalid citation)")
        if problems:
            failures.append(
                {"id": row["id"], "message": item["message"][:160], "problems": problems,
                 "decision_codes": row["decision_codes"]}
            )
    return failures[:limit]


def run_evaluation(
    dataset: dict[str, Any],
    *,
    retriever: Retriever,
    client: LLMClient,
    config: PipelineConfig,
    limit: int | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, Any]:
    items = dataset["items"][:limit] if limit else dataset["items"]
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        result = run_pipeline(item["message"], retriever=retriever, client=client, config=config)
        rows.append(evaluate_item(item, result))
        if progress:
            progress(index, len(items), item["id"])
    metrics = compute_metrics(items, rows)
    failures = collect_failures(items, rows)
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        for tag in row["tags"]:
            by_tag[tag].append(row)
    return {
        "model": client.model_name,
        "prompt_version": config.analyzer.prompt_version,
        "dataset_version": dataset.get("dataset_version", "unknown"),
        "dataset_size": len(items),
        "metrics": metrics,
        "failures": failures,
        "rows": rows,
        "tag_counts": {tag: len(group) for tag, group in sorted(by_tag.items())},
    }
