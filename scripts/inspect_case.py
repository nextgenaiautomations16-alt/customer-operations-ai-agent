"""Show exactly what the model said for chosen dataset messages (to diagnose evaluation failures).
    python scripts\\inspect_case.py N02 N05 N08 O01
    python scripts\\inspect_case.py N02 --backend heuristic     # offline check that the script works
"""
import argparse
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ai.factory import build_llm_client  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.evaluation.runner import load_dataset  # noqa: E402
from app.retrieval.retriever import Retriever  # noqa: E402
from app.services.pipeline import PipelineConfig, run_pipeline  # noqa: E402
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+", help="dataset ids, e.g. N02 O01")
    parser.add_argument("--backend", default=None)
    parser.add_argument("--model", default=None)
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
    config = PipelineConfig.from_settings(settings)
    items = {item["id"]: item for item in load_dataset(ROOT / settings.dataset_path)["items"]}
    for item_id in args.ids:
        item = items.get(item_id)
        if item is None:
            print(f"\n{item_id}: not in the dataset")
            continue
        result = run_pipeline(item["message"], retriever=retriever, client=client, config=config)
        outcome, decision = result.outcome, result.decision
        print("\n" + "=" * 78)
        print(f"{item_id}: {item['message']}")
        print(f"  expected     : category={item['expected_category']} sources={item['expected_sources']}")
        print(f"  retrieved    : {[(p.source_id, p.score) for p in result.passages]}")
        if outcome.analysis is None:
            print(f"  MODEL FAILED : {outcome.error_category} {outcome.error_detail}")
        else:
            a = outcome.analysis
            print(f"  model said   : category={a.category.value} action={a.recommended_action.value} "
                  f"confidence={a.confidence}")
            print(f"  cited_sources: {a.cited_sources}")
            print(f"  valid/invalid: {outcome.valid_citations} / {outcome.invalid_citations}")
        print(f"  decision     : status={decision.status.value} priority={decision.priority.value} "
              f"codes={list(decision.reasons)}")
        print(f"  took         : {outcome.latency_ms} ms, {outcome.attempts} attempt(s)")
    return 0
if __name__ == "__main__":
    sys.exit(main())
