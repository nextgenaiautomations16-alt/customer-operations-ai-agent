"""The Ollama HTTP client, tested against a fake transport (no Ollama needed)."""

import json

import httpx
import pytest

from app.ai.client import (
    LLMTimeoutError,
    LLMTransientError,
    LLMUnavailableError,
    OllamaClient,
)


def client_with(handler) -> OllamaClient:
    return OllamaClient(
        "http://ollama.test", "qwen-test", 5.0, transport=httpx.MockTransport(handler)
    )


def ok_response(text='{"a": 1}'):
    return httpx.Response(
        200, json={"message": {"content": text}, "prompt_eval_count": 11, "eval_count": 7}
    )


def test_success_returns_text_and_token_counts():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return ok_response()

    response = client_with(handler).generate("sys", "usr", json_schema={"type": "object"})
    assert response.text == '{"a": 1}'
    assert (response.prompt_tokens, response.completion_tokens) == (11, 7)
    assert seen["body"]["model"] == "qwen-test"
    assert seen["body"]["stream"] is False
    assert seen["body"]["options"]["temperature"] == 0
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}


def test_connection_refused_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(LLMUnavailableError):
        client_with(handler).generate("s", "u")


def test_timeout_is_a_timeout_error():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(LLMTimeoutError):
        client_with(handler).generate("s", "u")


def test_unknown_model_is_unavailable():
    with pytest.raises(LLMUnavailableError, match="not found"):
        client_with(lambda r: httpx.Response(404, json={"error": "model not found"})).generate("s", "u")


@pytest.mark.parametrize("status", [429, 500, 503])
def test_server_trouble_is_transient(status):
    with pytest.raises(LLMTransientError):
        client_with(lambda r: httpx.Response(status)).generate("s", "u")


def test_unexpected_response_shape_is_transient():
    with pytest.raises(LLMTransientError):
        client_with(lambda r: httpx.Response(200, json={"nope": True})).generate("s", "u")


def test_rejected_schema_falls_back_to_plain_json_mode():
    formats = []

    def handler(request):
        body = json.loads(request.content)
        formats.append(body["format"])
        return httpx.Response(400) if isinstance(body["format"], dict) else ok_response()

    response = client_with(handler).generate("s", "u", json_schema={"type": "object"})
    assert response.text and formats == [{"type": "object"}, "json"]


def test_ping():
    assert client_with(lambda r: httpx.Response(200, json={"models": []})).ping() is True

    def refuse(request):
        raise httpx.ConnectError("refused")

    assert client_with(refuse).ping() is False
