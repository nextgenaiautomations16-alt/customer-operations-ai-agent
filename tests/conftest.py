"""Shared test fixtures. No test here needs Ollama or the internet."""

import json
from pathlib import Path

import pytest

from app.ai.analyzer import AnalyzerConfig
from app.db.database import Database
from app.retrieval.retriever import Retriever
from app.services.cases import CaseService
from app.services.pipeline import PipelineConfig

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "data" / "knowledge_base"


def make_reply(**overrides) -> str:
    """A valid model reply as JSON text. Override any field to build a variant."""
    reply = {
        "category": "billing",
        "sentiment": "neutral",
        "urgency": "medium",
        "requested_resolution": "information",
        "prior_contacts": 0,
        "recommended_action": "reply_with_policy_info",
        "summary": "Customer asks a billing question.",
        "draft_reply": "Thanks for reaching out. Here is what our policy says.",
        "cited_sources": ["POL-BILL-002"],
        "confidence": 0.9,
    }
    reply.update(overrides)
    return json.dumps(reply)


@pytest.fixture(scope="session")
def retriever() -> Retriever:
    return Retriever.from_directory(KB_DIR)


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    database.init()
    return database


@pytest.fixture()
def pipeline_config() -> PipelineConfig:
    # No waiting between retries in tests.
    return PipelineConfig(analyzer=AnalyzerConfig(max_retries=2, backoff_seconds=0.0))


@pytest.fixture()
def make_service(db, retriever, pipeline_config):
    def _make(llm, kb: Retriever | None = None) -> CaseService:
        return CaseService(db, kb or retriever, llm, pipeline_config)

    return _make


def new_case(service: CaseService, message: str, key: str | None = None) -> dict:
    case, _ = service.create_case(
        message=message, customer_ref=None, idempotency_key=key, correlation_id="corr-test-0001"
    )
    return case


REFUND_MESSAGE = (
    "Hi, I was billed $49 twice for my March subscription. Could you refund the duplicate payment?"
)
EXPORT_MESSAGE = "How do I download all my account data before I leave? I want a full export."
SCENARIO_MESSAGE = (
    "My invoice was charged twice, and my account is still locked. "
    "I have already contacted support twice."
)
