"""Fake language models for tests and offline demos. They never touch the network.

IMPORTANT: results from these fakes say nothing about how a real model performs.
They exist so the pipeline, tests and demo can run without Ollama.
"""

import json
import re
from typing import Any

from app.ai.client import LLMError, LLMResponse
from app.core.signals import detect_signals, keyword_category


class ScriptedLLM:
    """Returns pre-written replies in order. An Exception in the list is raised instead.

    When the script runs out, the last item repeats (set ``repeat_last=False`` to fail loudly).
    """

    def __init__(
        self,
        replies: list[str | Exception | LLMResponse],
        model_name: str = "fake-scripted",
        repeat_last: bool = True,
    ) -> None:
        self._replies = list(replies)
        self._model = model_name
        self._repeat_last = repeat_last
        self.calls: list[tuple[str, str]] = []

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LLMResponse:
        self.calls.append((system, user))
        index = len(self.calls) - 1
        if index >= len(self._replies):
            if not self._repeat_last:
                raise AssertionError("ScriptedLLM ran out of replies")
            index = len(self._replies) - 1
        reply = self._replies[index]
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, LLMResponse):
            return reply
        return LLMResponse(text=reply, prompt_tokens=0, completion_tokens=0)

    def ping(self) -> bool:
        return True


_MESSAGE_RE = re.compile(r"<customer_message>\s*(.*?)\s*</customer_message>", re.DOTALL)
_SOURCE_RE = re.compile(r"\[source: ([A-Z0-9-]+) \|")


class HeuristicLLM:
    """A rule-based stand-in that reads the prompt and answers with plausible JSON.

    It uses the same keyword signals as the business rules, so it looks better on the
    evaluation than a real model would. Use it only for smoke tests and offline demos.
    """

    def __init__(self, model_name: str = "fake-heuristic") -> None:
        self._model = model_name

    @property
    def model_name(self) -> str:
        return self._model

    def ping(self) -> bool:
        return True

    def generate(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LLMResponse:
        match = _MESSAGE_RE.search(user)
        message = match.group(1) if match else ""
        sources = list(dict.fromkeys(_SOURCE_RE.findall(user)))
        signals = detect_signals(message)
        category = keyword_category(message, signals)

        if signals.security or signals.legal or signals.outage or signals.injection:
            action = "escalate_to_human"
        elif signals.double_charge or signals.refund_request:
            action = "refund_review"
        elif signals.locked_out:
            action = "account_unlock_review"
        elif sources:
            action = "reply_with_policy_info"
        else:
            action = "request_more_info"

        negative = signals.prior_contacts > 0 or any(
            w in message.lower() for w in ("angry", "unacceptable", "terrible", "frustrat")
        )
        positive = any(w in message.lower() for w in ("thank", "great service"))
        sentiment = "negative" if negative else ("positive" if positive else "neutral")
        resolution = (
            "refund"
            if (signals.double_charge or signals.refund_request)
            else "account_access"
            if signals.locked_out
            else "fix_issue"
            if category.value == "technical"
            else "information"
        )
        cited = sources[:2] if action not in ("request_more_info",) else []
        reply = {
            "category": category.value,
            "sentiment": sentiment,
            "urgency": "high" if signals.prior_contacts >= 2 or signals.security else "medium",
            "requested_resolution": resolution,
            "prior_contacts": signals.prior_contacts,
            "recommended_action": action,
            "summary": "Customer message triaged by the heuristic fake model.",
            "draft_reply": "Thank you for contacting us. A team member is reviewing your request.",
            "cited_sources": cited,
            "confidence": 0.9 if sources or action == "escalate_to_human" else 0.5,
        }
        return LLMResponse(text=json.dumps(reply), prompt_tokens=0, completion_tokens=0)


class AlwaysFailingLLM:
    """Simulates an unavailable model, for failure-path demos."""

    def __init__(self, error: LLMError | None = None) -> None:
        from app.ai.client import LLMUnavailableError

        self._error = error or LLMUnavailableError("Simulated: model unavailable")

    @property
    def model_name(self) -> str:
        return "fake-unavailable"

    def ping(self) -> bool:
        return False

    def generate(
        self, system: str, user: str, *, json_schema: dict[str, Any] | None = None
    ) -> LLMResponse:
        raise self._error
