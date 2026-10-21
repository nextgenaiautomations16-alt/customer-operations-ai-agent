"""Request and response shapes for the HTTP API."""

from typing import Any

from pydantic import BaseModel, Field, field_validator


class CaseCreate(BaseModel):
    message: str = Field(
        min_length=3,
        max_length=4000,
        description="The customer's message. Use synthetic text only.",
        examples=[
            "My invoice was charged twice, and my account is still locked. "
            "I have already contacted support twice."
        ],
    )
    customer_ref: str | None = Field(
        default=None,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.\-]+$",
        description="Optional synthetic customer reference, e.g. CUST-1001. Not an email or name.",
    )

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("message must contain at least 3 non-space characters")
        return value


class ReviewAction(BaseModel):
    reviewer: str = Field(min_length=2, max_length=80, description="Who is making this decision.")
    note: str | None = Field(default=None, max_length=1000)


class EvaluationRequest(BaseModel):
    limit: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Only run the first N messages. Full runs are better done with scripts/run_eval.py.",
    )


class CaseOut(BaseModel):
    id: str
    created_at: str
    updated_at: str
    status: str
    message: str
    customer_ref: str | None = None
    category: str | None = None
    priority: str | None = None
    consequential: bool
    automation_candidate: bool
    decision_codes: list[str]


class RecommendationOut(BaseModel):
    case_id: str
    case_status: str
    case: CaseOut
    run: dict[str, Any]


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    correlation_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
