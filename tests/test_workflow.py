import pytest

from app.core.enums import CaseStatus
from app.core.errors import InvalidTransitionError, NoteRequiredError
from app.core.workflow import (
    ALLOWED_TRANSITIONS,
    can_transition,
    check_can_approve,
    check_can_reject,
    check_can_resolve,
)

S = CaseStatus


def test_every_status_has_an_entry():
    assert set(ALLOWED_TRANSITIONS) == set(CaseStatus)


def test_resolved_is_terminal():
    assert ALLOWED_TRANSITIONS[S.RESOLVED] == frozenset()


def test_nothing_reaches_approved_except_from_pending_review():
    sources = [s for s in CaseStatus if can_transition(s, S.APPROVED)]
    assert sources == [S.PENDING_REVIEW]


def test_nothing_reaches_rejected_except_from_pending_review():
    assert [s for s in CaseStatus if can_transition(s, S.REJECTED)] == [S.PENDING_REVIEW]


@pytest.mark.parametrize("status", [s for s in CaseStatus if s != S.PENDING_REVIEW])
def test_cannot_approve_from_other_states(status):
    with pytest.raises(InvalidTransitionError):
        check_can_approve(status, consequential=False, note="a perfectly good note")


def test_consequential_approval_needs_a_real_note():
    with pytest.raises(NoteRequiredError):
        check_can_approve(S.PENDING_REVIEW, consequential=True, note="ok")
    with pytest.raises(NoteRequiredError):
        check_can_approve(S.PENDING_REVIEW, consequential=True, note=None)
    assert check_can_approve(S.PENDING_REVIEW, consequential=True, note="Verified duplicate") == (
        "Verified duplicate"
    )


def test_non_consequential_approval_note_is_optional():
    assert check_can_approve(S.PENDING_REVIEW, consequential=False, note=None) is None


def test_reject_requires_note():
    with pytest.raises(NoteRequiredError):
        check_can_reject(S.PENDING_REVIEW, note="")


@pytest.mark.parametrize("status", [S.APPROVED, S.REJECTED, S.ESCALATED])
def test_resolve_allowed_from_decided_or_escalated(status):
    assert check_can_resolve(status, note="Closed after follow up") == "Closed after follow up"


@pytest.mark.parametrize("status", [S.NEW, S.PENDING_REVIEW, S.PROCESSING_FAILED, S.RESOLVED])
def test_resolve_blocked_elsewhere(status):
    with pytest.raises(InvalidTransitionError):
        check_can_resolve(status, note="Closed after follow up")


def test_failed_processing_can_be_retried():
    assert can_transition(S.PROCESSING_FAILED, S.PENDING_REVIEW)
    assert can_transition(S.PROCESSING_FAILED, S.PROCESSING_FAILED)
