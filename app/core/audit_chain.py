"""Hash chain for the audit log (pure functions, no database access).

Every audit event stores the hash of the event before it (``prev_hash``) and its own
hash (``event_hash``), which covers all of its fields plus ``prev_hash``. If someone edits
or deletes an event in the middle of the log, the chain no longer lines up and
``verify_chain`` reports where it broke.

Honest limits (also documented in docs/security.md):
- Someone with write access to the database could rewrite the *whole* chain consistently.
- Removing events from the very end of the log cannot be detected from inside the
  database. Keep ``head_hash`` somewhere else (a ticket, an email, a CI log) to detect that.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.core.hashing import canonical_json, sha256_text

GENESIS_HASH = "0" * 64

# Every field below is covered by the event hash.
HASHED_FIELDS = (
    "event_id",
    "case_id",
    "event_type",
    "actor_type",
    "outcome",
    "correlation_id",
    "prompt_version",
    "model",
    "input_hash",
    "output_hash",
    "approval_status",
    "error_category",
    "details",
    "created_at",
    "prev_hash",
)


def compute_event_hash(record: Mapping[str, Any]) -> str:
    payload = {name: record.get(name) for name in HASHED_FIELDS}
    return sha256_text(canonical_json(payload))


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    events_checked: int
    head_hash: str
    first_invalid_seq: int | None = None
    reason: str | None = None


def verify_chain(records: Iterable[Mapping[str, Any]]) -> VerifyResult:
    """Check events in the order they were written (ascending ``seq``)."""
    previous_hash = GENESIS_HASH
    checked = 0
    for record in records:
        checked += 1
        seq = record.get("seq")
        if record.get("prev_hash") != previous_hash:
            return VerifyResult(
                valid=False,
                events_checked=checked,
                head_hash=previous_hash,
                first_invalid_seq=seq,
                reason="prev_hash does not match the previous event "
                "(an event was removed, inserted or reordered)",
            )
        if record.get("event_hash") != compute_event_hash(record):
            return VerifyResult(
                valid=False,
                events_checked=checked,
                head_hash=previous_hash,
                first_invalid_seq=seq,
                reason="event content does not match its stored hash (event was modified)",
            )
        previous_hash = record["event_hash"]
    return VerifyResult(valid=True, events_checked=checked, head_hash=previous_hash)
