"""Deterministic business rules: priority, escalation and approval requirements.

The AI *suggests* (category, action, draft reply). These rules *decide* what happens next.
Decision codes starting with ``E_`` send the case to a person (escalated). ``R_`` marks a
system condition, ``N_`` is an informational note.
"""

from dataclasses import dataclass

from app.core.enums import Action, CaseStatus, Category, Priority
from app.core.signals import Signals, keyword_category
from app.schemas.ai import AIAnalysis

# Actions that move money or change an account. A human must approve these with a note.
CONSEQUENTIAL_ACTIONS = frozenset({Action.REFUND_REVIEW, Action.ACCOUNT_UNLOCK_REVIEW})

# Actions that do not need a policy citation to be acceptable.
NO_CITATION_NEEDED = frozenset({Action.REQUEST_MORE_INFO, Action.ESCALATE_TO_HUMAN, Action.NO_ACTION})

AUTOMATION_CONFIDENCE = 0.8


@dataclass(frozen=True)
class Decision:
    priority: Priority
    status: CaseStatus
    reasons: tuple[str, ...]
    consequential: bool
    automation_candidate: bool


def compute_priority(category: Category, signals: Signals) -> Priority:
    """Priority policy v1 (see docs/design.md). The AI's own 'urgency' is advisory only."""
    if (
        signals.security
        or signals.legal
        or signals.outage
        or (signals.double_charge and signals.locked_out)
        or signals.prior_contacts >= 2
    ):
        return Priority.HIGH
    if category in (Category.BILLING, Category.ACCOUNT_ACCESS):
        return Priority.MEDIUM
    if category == Category.TECHNICAL and signals.problem_words:
        return Priority.MEDIUM
    return Priority.LOW


def decide(
    *,
    message: str,
    signals: Signals,
    analysis: AIAnalysis | None,
    grounded: bool,
    fabricated_citation: bool,
    min_confidence: float,
) -> Decision:
    """Turn signals plus (optional) AI output into a priority and a next status."""
    hard_reasons = signals.hard_escalation_reasons
    keyword_guess = keyword_category(message, signals)

    # --- The model failed or returned nothing usable -------------------------------------
    if analysis is None:
        priority = compute_priority(keyword_guess, signals)
        reasons = ["R_MODEL_FAILURE", *hard_reasons]
        status = CaseStatus.ESCALATED if hard_reasons else CaseStatus.PROCESSING_FAILED
        consequential = signals.double_charge or signals.refund_request or signals.security
        return Decision(priority, status, tuple(reasons), consequential, False)

    # --- Normal path ------------------------------------------------------------------------
    action = analysis.recommended_action
    priority = compute_priority(analysis.category, signals)
    reasons = list(hard_reasons)
    # The AI's own count of earlier contacts can also trigger the repeat-contact rule.
    if analysis.prior_contacts >= 2 and "E_REPEAT_CONTACT" not in reasons:
        reasons.append("E_REPEAT_CONTACT")
        priority = Priority.HIGH

    if action == Action.ESCALATE_TO_HUMAN:
        reasons.append("E_AI_REQUESTED_ESCALATION")
    if analysis.confidence < min_confidence:
        reasons.append("E_LOW_CONFIDENCE")
    if fabricated_citation:
        reasons.append("E_FABRICATED_CITATION")
    elif not grounded and action not in NO_CITATION_NEEDED:
        reasons.append("E_NO_POLICY_SUPPORT")
    if analysis.category != keyword_guess and keyword_guess != Category.OTHER:
        reasons.append("N_KEYWORD_CATEGORY_MISMATCH")

    escalated = any(code.startswith("E_") for code in reasons)
    status = CaseStatus.ESCALATED if escalated else CaseStatus.PENDING_REVIEW

    consequential = (
        action in CONSEQUENTIAL_ACTIONS
        or signals.double_charge
        or signals.refund_request
        or signals.security
    )
    automation_candidate = (
        status == CaseStatus.PENDING_REVIEW
        and action == Action.REPLY_WITH_POLICY_INFO
        and grounded
        and analysis.confidence >= AUTOMATION_CONFIDENCE
        and not consequential
    )
    return Decision(priority, status, tuple(reasons), consequential, automation_candidate)
