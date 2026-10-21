"""Case status rules: which moves are allowed and what a human must supply.

These are plain functions with no database access, so they are easy to test and easy to
read in an interview. The API and services call them; the AI layer never does.
"""

from app.core.enums import CaseStatus
from app.core.errors import InvalidTransitionError, NoteRequiredError

S = CaseStatus

ALLOWED_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    S.NEW: frozenset({S.PENDING_REVIEW, S.ESCALATED, S.PROCESSING_FAILED}),
    # Retry = process the case again. It can end in any of the three processing outcomes.
    S.PROCESSING_FAILED: frozenset({S.PENDING_REVIEW, S.ESCALATED, S.PROCESSING_FAILED}),
    S.PENDING_REVIEW: frozenset({S.APPROVED, S.REJECTED}),
    S.ESCALATED: frozenset({S.RESOLVED}),
    S.APPROVED: frozenset({S.RESOLVED}),
    S.REJECTED: frozenset({S.RESOLVED}),
    S.RESOLVED: frozenset(),
}

# States from which /process is allowed.
PROCESSABLE = frozenset({S.NEW, S.PROCESSING_FAILED})

MIN_CONSEQUENTIAL_NOTE_LENGTH = 10
MIN_NOTE_LENGTH = 5


def can_transition(current: CaseStatus, target: CaseStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def assert_transition(current: CaseStatus, target: CaseStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(
            f"Cannot move a case from '{current.value}' to '{target.value}'.",
            details={"current": current.value, "target": target.value},
        )


def require_note(note: str | None, *, minimum: int, what: str) -> str:
    cleaned = (note or "").strip()
    if len(cleaned) < minimum:
        raise NoteRequiredError(
            f"{what} requires a note of at least {minimum} characters.",
            details={"minimum_length": minimum},
        )
    return cleaned


def check_can_approve(status: CaseStatus, *, consequential: bool, note: str | None) -> str | None:
    """Raise unless a human may approve now. Returns the cleaned note (may be None)."""
    assert_transition(status, S.APPROVED)
    if consequential:
        return require_note(
            note, minimum=MIN_CONSEQUENTIAL_NOTE_LENGTH, what="Approving a consequential action"
        )
    cleaned = (note or "").strip()
    return cleaned or None


def check_can_reject(status: CaseStatus, *, note: str | None) -> str:
    assert_transition(status, S.REJECTED)
    return require_note(note, minimum=MIN_NOTE_LENGTH, what="Rejecting a recommendation")


def check_can_resolve(status: CaseStatus, *, note: str | None) -> str:
    assert_transition(status, S.RESOLVED)
    return require_note(note, minimum=MIN_NOTE_LENGTH, what="Resolving a case")
