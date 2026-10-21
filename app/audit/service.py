"""Append-only audit log with a hash chain.

The application only ever INSERTs audit rows (this module has no update or delete). That is
an *application-level* rule. Anyone with direct access to the SQLite file can still edit it;
the hash chain makes such edits detectable but does not prevent them. See docs/security.md.
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from app.core.audit_chain import GENESIS_HASH, VerifyResult, compute_event_hash, verify_chain
from app.core.enums import ActorType
from app.core.hashing import canonical_json


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def append_event(
    conn: sqlite3.Connection,
    *,
    case_id: str | None,
    event_type: str,
    actor_type: ActorType,
    outcome: str,
    correlation_id: str | None = None,
    prompt_version: str | None = None,
    model: str | None = None,
    input_hash: str | None = None,
    output_hash: str | None = None,
    approval_status: str | None = None,
    error_category: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert one event. Must be called inside ``write_tx`` so the chain stays consistent."""
    last = conn.execute("SELECT event_hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    record: dict[str, Any] = {
        "event_id": "evt_" + uuid.uuid4().hex[:16],
        "case_id": case_id,
        "event_type": event_type,
        "actor_type": actor_type.value,
        "outcome": outcome,
        "correlation_id": correlation_id,
        "prompt_version": prompt_version,
        "model": model,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "approval_status": approval_status,
        "error_category": error_category,
        "details": canonical_json(details) if details else None,
        "created_at": utc_now(),
        "prev_hash": last["event_hash"] if last else GENESIS_HASH,
    }
    record["event_hash"] = compute_event_hash(record)
    columns = ", ".join(record)
    placeholders = ", ".join(f":{name}" for name in record)
    conn.execute(f"INSERT INTO audit_events ({columns}) VALUES ({placeholders})", record)
    return record


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["details"] = json.loads(data["details"]) if data["details"] else None
    return data


def events_for_case(conn: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM audit_events WHERE case_id = ? ORDER BY seq", (case_id,)
    ).fetchall()
    return [_row_to_event(row) for row in rows]


def recent_events(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM audit_events ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_event(row) for row in rows]


def verify_audit_log(conn: sqlite3.Connection) -> VerifyResult:
    rows = conn.execute("SELECT * FROM audit_events ORDER BY seq").fetchall()
    return verify_chain(dict(row) for row in rows)
