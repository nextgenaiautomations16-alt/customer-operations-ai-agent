"""Run the evaluation from the command line and write a report.

Examples (PowerShell, from the project folder with the virtual environment active):

    python scripts\\run_eval.py --backend ollama --model qwen2.5:7b
    python scripts\\run_eval.py --backend heuristic      # fake model, offline smoke test only
    python scripts\\run_eval.py --backend ollama --limit 5   # quick trial of 5 messages
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ai.factory import build_llm_client  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.evaluation.report import render_markdown  # noqa: E402
from app.evaluation.runner import load_dataset, run_evaluation  # noqa: E402
from app.retrieval.retriever import Retriever  # noqa: E402
from app.services.pipeline import PipelineConfig  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the triage pipeline on the labelled dataset.")
    parser.add_argument("--backend", default=None, help="ollama | heuristic | unavailable")
    parser.add_argument("--model", default=None, help="Ollama model name, e.g. qwen2.5:7b")
    parser.add_argument("--dataset", default=str(ROOT / "data" / "synthetic_cases.json"))
    parser.add_argument("--out", default=str(ROOT / "reports"))
    parser.add_argument("--limit", type=int, default=None, help="only the first N messages")
    parser.add_argument("--label", default="", help="short name added to the report filename")
    args = parser.parse_args()

    settings = Settings.load(ROOT / ".env")
    overrides = {}
    if args.backend:
        overrides["llm_backend"] = args.backend
    if args.model:
        overrides["ollama_model"] = args.model
    if overrides:
        settings = Settings(**{**settings.__dict__, **overrides})

    client = build_llm_client(settings)
    retriever = Retriever.from_directory(ROOT / settings.knowledge_base_dir)
    dataset = load_dataset(args.dataset)
    config = PipelineConfig.from_settings(settings)

    print(f"Model: {client.model_name} | prompt {config.analyzer.prompt_version} | "
          f"{len(dataset['items'][: args.limit] if args.limit else dataset['items'])} messages")
    if client.model_name.startswith("fake-"):
        print("NOTE: fake model. Numbers only test the pipeline, not real model quality.")

    def progress(done: int, total: int, item_id: str) -> None:
        print(f"  [{done}/{total}] {item_id}", flush=True)

    result = run_evaluation(
        dataset, retriever=retriever, client=client, config=config,
        limit=args.limit, progress=progress,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    safe_model = client.model_name.replace(":", "-").replace("/", "-")
    name = f"eval-{safe_model}{('-' + args.label) if args.label else ''}-{stamp}"
    (out_dir / f"{name}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / f"{name}.md").write_text(render_markdown(result), encoding="utf-8")
    (out_dir / "latest.md").write_text(render_markdown(result), encoding="utf-8")

    metrics = result["metrics"]
    print("\nHeadline:")
    for key in ("category_accuracy", "keyword_baseline_category_accuracy", "priority_accuracy",
                "escalation_accuracy", "structured_output_validity", "model_failure_rate",
                "grounded_recommendation_rate", "unsupported_claim_rate", "latency_ms_p50"):
        print(f"  {key}: {metrics[key]}")
    print(f"\nWrote {out_dir / (name + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
