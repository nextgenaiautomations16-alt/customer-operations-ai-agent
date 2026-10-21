"""SQLite access with the standard library (no ORM).

Why plain sqlite3 instead of SQLAlchemy? For five tables it is simpler to read and to
explain, and it has no install step. The trade-off: moving to PostgreSQL means rewriting
these queries (or adopting SQLAlchemy at that point). See docs/design.md.

Connections are opened per request and used in autocommit mode; write operations wrap their
work in ``write_tx`` which uses BEGIN IMMEDIATE so two writers cannot interleave.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.enums import (
    AIRunStatus,
    CaseStatus,
    Category,
    DecisionKind,
    Priority,
    values,
)


def _in(enum_cls: type) -> str:
    return ", ".join(f"'{v}'" for v in values(enum_cls))


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({_in(CaseStatus)})),
    message TEXT NOT NULL CHECK (length(message) BETWEEN 1 AND 4000),
    customer_ref TEXT,
    idempotency_key TEXT UNIQUE,
    request_hash TEXT NOT NULL,
    category TEXT CHECK (category IS NULL OR category IN ({_in(Category)})),
    priority TEXT CHECK (priority IS NULL OR priority IN ({_in(Priority)})),
    consequential INTEGER NOT NULL DEFAULT 0 CHECK (consequential IN (0, 1)),
    automation_candidate INTEGER NOT NULL DEFAULT 0 CHECK (automation_candidate IN (0, 1)),
    decision_codes TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);

CREATE TABLE IF NOT EXISTS ai_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    created_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ({_in(AIRunStatus)})),
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL,
    error_category TEXT,
    error_detail TEXT,
    analysis_json TEXT,
    cited_valid TEXT NOT NULL DEFAULT '[]',
    cited_invalid TEXT NOT NULL DEFAULT '[]',
    grounded INTEGER NOT NULL DEFAULT 0 CHECK (grounded IN (0, 1)),
    retrieved_sources TEXT NOT NULL DEFAULT '[]',
    output_hash TEXT,
    correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_runs_case ON ai_runs(case_id);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL REFERENCES cases(id),
    decision TEXT NOT NULL CHECK (decision IN ({_in(DecisionKind)})),
    reviewer TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_approvals_case ON approvals(case_id);

CREATE TABLE IF NOT EXISTS audit_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    case_id TEXT,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL CHECK (actor_type IN ('system', 'ai', 'human')),
    outcome TEXT NOT NULL,
    correlation_id TEXT,
    prompt_version TEXT,
    model TEXT,
    input_hash TEXT,
    output_hash TEXT,
    approval_status TEXT,
    error_category TEXT,
    details TEXT,
    created_at TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    event_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_events(case_id);

CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    dataset_size INTEGER NOT NULL,
    metrics_json TEXT NOT NULL,
    failures_json TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        return conn

    def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block as one all-or-nothing transaction that holds the write lock."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
