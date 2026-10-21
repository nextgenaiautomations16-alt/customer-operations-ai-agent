"""The structure the language model must return. Anything else is rejected."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.enums import Action, Category, RequestedResolution, Sentiment, Urgency

SUMMARY_MAX = 300
REPLY_MAX = 1000


def _clean_text(value: Any, limit: int) -> Any:
    """Strip and trim over-long text. Non-strings are left alone so validation rejects them."""
    if isinstance(value, str):
        return value.strip()[:limit]
    return value


class AIAnalysis(BaseModel):
    category: Category
    sentiment: Sentiment
    urgency: Urgency
    requested_resolution: RequestedResolution
    prior_contacts: int = Field(default=0, ge=0, le=20)
    recommended_action: Action
    summary: str = Field(min_length=1)
    draft_reply: str = Field(min_length=1)
    cited_sources: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("summary", mode="before")
    @classmethod
    def _trim_summary(cls, value: Any) -> Any:
        return _clean_text(value, SUMMARY_MAX)

    @field_validator("draft_reply", mode="before")
    @classmethod
    def _trim_reply(cls, value: Any) -> Any:
        return _clean_text(value, REPLY_MAX)

    @field_validator("cited_sources", mode="before")
    @classmethod
    def _strip_sources(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value
