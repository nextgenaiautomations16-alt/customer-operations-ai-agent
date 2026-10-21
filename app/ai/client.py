"""Language-model clients. Only Ollama (local, free) is implemented for real use.

Error classes tell the caller how to react:
- LLMUnavailableError: the model cannot be reached or does not exist -> do not retry.
- LLMTimeoutError / LLMTransientError: might work next time -> retry a limited number of times.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass
class LLMResponse:
    text: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMError(Exception):
    category = "llm_error"


class LLMUnavailableError(LLMError):
    category = "unavailable"


class LLMTimeoutError(LLMError):
    category = "timeout"


class LLMTransientError(LLMError):
    category = "transient"


class LLMClient(Protocol):
    @property
    def model_name(self) -> str: ...

    def generate(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LLMResponse: ...

    def ping(self) -> bool: ...


class OllamaClient:
    """Talks to a local Ollama server over HTTP (POST /api/chat)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport  # tests inject a fake transport here

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Temperature 0 makes runs repeatable, which matters for the evaluation.
            "options": {"temperature": 0},
            "format": json_schema if json_schema is not None else "json",
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(f"{self._base_url}/api/chat", json=payload)
                if response.status_code == 400 and json_schema is not None:
                    # Some Ollama versions reject a full JSON schema; fall back to plain JSON mode.
                    payload["format"] = "json"
                    response = client.post(f"{self._base_url}/api/chat", json=payload)
        except httpx.ConnectError as error:
            raise LLMUnavailableError("Cannot connect to Ollama (is it running?)") from error
        except httpx.TimeoutException as error:
            raise LLMTimeoutError(f"Ollama did not answer within {self._timeout} seconds") from error
        except httpx.HTTPError as error:
            raise LLMTransientError(f"Network problem talking to Ollama: {type(error).__name__}") from error

        if response.status_code == 404:
            raise LLMUnavailableError(f"Model '{self._model}' not found in Ollama")
        if response.status_code == 429 or response.status_code >= 500:
            raise LLMTransientError(f"Ollama returned HTTP {response.status_code}")
        if response.status_code >= 400:
            raise LLMUnavailableError(f"Ollama rejected the request (HTTP {response.status_code})")

        try:
            body = response.json()
            text = body["message"]["content"]
        except (ValueError, KeyError, TypeError) as error:
            raise LLMTransientError("Ollama returned an unexpected response shape") from error
        if not isinstance(text, str):
            raise LLMTransientError("Ollama returned non-text content")
        return LLMResponse(
            text=text,
            prompt_tokens=body.get("prompt_eval_count"),
            completion_tokens=body.get("eval_count"),
        )

    def ping(self) -> bool:
        """Quick reachability check used by GET /health?deep=true."""
        try:
            with httpx.Client(timeout=2.0, transport=self._transport) as client:
                return client.get(f"{self._base_url}/api/tags").status_code == 200
        except httpx.HTTPError:
            return False
