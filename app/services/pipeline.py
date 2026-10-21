"""The processing pipeline for one customer message. No database, so it is easy to test.

signals -> retrieval -> AI analysis -> deterministic decision

Both the API (``process_case``) and the evaluation runner call this same function, so the
evaluation measures exactly what the API does.
"""

import time
from dataclasses import dataclass
from typing import Any

from app.ai.analyzer import AnalysisOutcome, AnalyzerConfig, analyze
from app.ai.client import LLMClient
from app.core.rules import Decision, decide
from app.core.signals import Signals, detect_signals
from app.retrieval.retriever import Passage, Retriever


@dataclass(frozen=True)
class PipelineConfig:
    retrieval_k: int = 3
    retrieval_min_score: float = 3.0
    min_confidence: float = 0.6
    analyzer: AnalyzerConfig = AnalyzerConfig()

    @classmethod
    def from_settings(cls, settings: Any) -> "PipelineConfig":
        return cls(
            retrieval_min_score=settings.retrieval_min_score,
            min_confidence=settings.min_confidence,
            analyzer=AnalyzerConfig(
                max_retries=settings.llm_max_retries,
                backoff_seconds=settings.llm_retry_backoff_seconds,
                prompt_version=settings.prompt_version,
            ),
        )


@dataclass
class PipelineResult:
    signals: Signals
    passages: list[Passage]
    outcome: AnalysisOutcome
    decision: Decision
    retrieval_ms: int
    total_ms: int


def run_pipeline(
    message: str,
    *,
    retriever: Retriever,
    client: LLMClient,
    config: PipelineConfig,
) -> PipelineResult:
    started = time.perf_counter()
    signals = detect_signals(message)

    retrieval_started = time.perf_counter()
    passages = retriever.search(
        message, k=config.retrieval_k, min_score=config.retrieval_min_score
    )
    retrieval_ms = int((time.perf_counter() - retrieval_started) * 1000)

    outcome = analyze(message, passages, client, config.analyzer)
    decision = decide(
        message=message,
        signals=signals,
        analysis=outcome.analysis,
        grounded=outcome.grounded,
        fabricated_citation=bool(outcome.invalid_citations),
        min_confidence=config.min_confidence,
    )
    return PipelineResult(
        signals=signals,
        passages=passages,
        outcome=outcome,
        decision=decision,
        retrieval_ms=retrieval_ms,
        total_ms=int((time.perf_counter() - started) * 1000),
    )
