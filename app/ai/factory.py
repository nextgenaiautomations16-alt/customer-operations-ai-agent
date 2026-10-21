"""Choose the language-model client from settings."""

from app.ai.client import LLMClient, OllamaClient
from app.ai.fakes import AlwaysFailingLLM, HeuristicLLM
from app.core.config import Settings


def build_llm_client(settings: Settings) -> LLMClient:
    backend = settings.llm_backend.lower()
    if backend == "ollama":
        return OllamaClient(
            settings.ollama_base_url, settings.ollama_model, settings.ollama_timeout_seconds
        )
    if backend == "heuristic":
        return HeuristicLLM()
    if backend == "unavailable":
        return AlwaysFailingLLM()
    raise ValueError(
        f"Unknown LLM_BACKEND '{settings.llm_backend}'. Use ollama, heuristic or unavailable."
    )
