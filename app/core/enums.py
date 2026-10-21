"""Shared vocabulary: every fixed set of allowed values lives here."""

from enum import Enum


class CaseStatus(str, Enum):
    NEW = "new"
    PROCESSING_FAILED = "processing_failed"
    PENDING_REVIEW = "pending_review"
    ESCALATED = "escalated"
    APPROVED = "approved"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class Category(str, Enum):
    BILLING = "billing"
    ACCOUNT_ACCESS = "account_access"
    TECHNICAL = "technical"
    OTHER = "other"


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Sentiment(str, Enum):
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"


class Urgency(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RequestedResolution(str, Enum):
    REFUND = "refund"
    ACCOUNT_ACCESS = "account_access"
    FIX_ISSUE = "fix_issue"
    INFORMATION = "information"
    CANCELLATION = "cancellation"
    NONE = "none"


class Action(str, Enum):
    """What the AI may *recommend*. None of these is executed by the system."""

    REPLY_WITH_POLICY_INFO = "reply_with_policy_info"
    REQUEST_MORE_INFO = "request_more_info"
    REFUND_REVIEW = "refund_review"
    ACCOUNT_UNLOCK_REVIEW = "account_unlock_review"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    NO_ACTION = "no_action"


class ActorType(str, Enum):
    SYSTEM = "system"
    AI = "ai"
    HUMAN = "human"


class AIRunStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


class DecisionKind(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


def values(enum_cls: type[Enum]) -> list[str]:
    """List the string values of an Enum (used for database check constraints)."""
    return [member.value for member in enum_cls]
