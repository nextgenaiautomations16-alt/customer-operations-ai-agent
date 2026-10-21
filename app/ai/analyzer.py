"""Ask the model for a structured analysis, validate it, and check it against the evidence.

What this module guarantees:
- The model's reply is parsed and validated against ``AIAnalysis``. Bad replies never reach
  the database as if they were good.
- Retries are bounded. Transient problems (timeouts, 5xx) and invalid output are retried;
  an unavailable model is not.
- Every citation is checked against the passages that were actually retrieved. Invented
  source IDs are flagged, not trusted.
- Failures are returned as data (``error_category``), not raised, so the caller can fall
  back to human review.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.ai.client import (
    LLMClient,
    LLMError,
    LLMTimeoutError,
    LLMTransientError,
    LLMUnavailableError,
)
from app.ai.prompts import REPAIR_NOTE, build_prompt
from app.core.hashing import sha256_text
from app.core.rules import NO_CITATION_NEEDED
from app.retrieval.retriever import Passage
from app.schemas.ai import AIAnalysis


@dataclass(frozen=True)
class AnalyzerConfig:
    max_retries: int = 2
    backoff_seconds: float = 0.5
    prompt_version: str = "v1"


@dataclass
class AnalysisOutcome:
    ok: bool
    model: str
    prompt_version: str
    attempts: int
    latency_ms: int
    analysis: AIAnalysis | None = None
    valid_citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    grounded: bool = False
    unsupported_claim: bool = False
    first_attempt_valid: bool = False
    error_category: str | None = None
    error_detail: str | None = None
    output_hash: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0


def extract_json_object(text: str) -> str:
    """Pull the JSON object out of a reply that may be wrapped in a markdown code fence."""
    stripped = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.DOTALL | re.IGNORECASE)
    if fence:
        stripped = fence.group(1)
    start, end = stripped.find("{"), stripped.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in the model reply")
    return stripped[start : end + 1]


def parse_analysis(text: str) -> AIAnalysis:
    """Parse and validate. Raises ValueError (including pydantic.ValidationError) if invalid."""
    return AIAnalysis.model_validate_json(extract_json_object(text))


def check_citations(
    analysis: AIAnalysis, passages: Sequence[Passage]
) -> tuple[list[str], list[str], bool, bool]:
    """Compare cited source IDs with the passages that were really retrieved.

    Returns (valid, invalid, grounded, unsupported_claim).
    - grounded: at least one valid citation.
    - unsupported_claim: a cited ID that was never retrieved (fabricated), or a substantive
      recommendation with no valid citation at all.
    """
    retrieved = {p.source_id for p in passages}
    cited = list(dict.fromkeys(analysis.cited_sources))
    valid = [c for c in cited if c in retrieved]
    invalid = [c for c in cited if c not in retrieved]
    grounded = bool(valid)
    substantive = analysis.recommended_action not in NO_CITATION_NEEDED
    unsupported = bool(invalid) or (substantive and not valid)
    return valid, invalid, grounded, unsupported


def analyze(
    message: str,
    passages: Sequence[Passage],
    client: LLMClient,
    config: AnalyzerConfig,
    json_schema: dict | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> AnalysisOutcome:
    system, user = build_prompt(config.prompt_version, message, passages)
    schema = json_schema if json_schema is not None else AIAnalysis.model_json_schema()
    max_attempts = 1 + max(0, config.max_retries)
    started = time.perf_counter()

    outcome = AnalysisOutcome(
        ok=False,
        model=client.model_name,
        prompt_version=config.prompt_version,
        attempts=0,
        latency_ms=0,
    )
    repair = ""

    for attempt in range(1, max_attempts + 1):
        outcome.attempts = attempt
        try:
            response = client.generate(system, user + repair, json_schema=schema)
        except LLMUnavailableError as error:
            outcome.error_category, outcome.error_detail = error.category, str(error)[:200]
            break  # retrying will not help
        except (LLMTimeoutError, LLMTransientError) as error:
            outcome.error_category, outcome.error_detail = error.category, str(error)[:200]
            if attempt < max_attempts:
                sleep(config.backoff_seconds * attempt)
            continue
        except LLMError as error:
            outcome.error_category, outcome.error_detail = error.category, str(error)[:200]
            break

        outcome.prompt_tokens += response.prompt_tokens or 0
        outcome.completion_tokens += response.completion_tokens or 0
        try:
            analysis = parse_analysis(response.text)
        except ValueError as error:
            # Keep only the error type and count, never echo model output or customer text.
            error_count = error.error_count() if hasattr(error, "error_count") else 1
            outcome.error_category = "invalid_output"
            outcome.error_detail = f"{type(error).__name__} ({error_count} problem(s))"
            repair = REPAIR_NOTE
            continue

        valid, invalid, grounded, unsupported = check_citations(analysis, passages)
        outcome.ok = True
        outcome.analysis = analysis
        outcome.valid_citations = valid
        outcome.invalid_citations = invalid
        outcome.grounded = grounded
        outcome.unsupported_claim = unsupported
        outcome.first_attempt_valid = attempt == 1
        outcome.output_hash = sha256_text(response.text)
        outcome.error_category = None
        outcome.error_detail = None
        break

    outcome.latency_ms = int((time.perf_counter() - started) * 1000)
    return outcome
