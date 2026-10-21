"""Case lifecycle: create, process, approve, reject, resolve, read, metrics.

Rules this module enforces (all server-side):
- Only the human endpoints (approve / reject / resolve) can set approved, rejected or resolved.
  The AI path (``process_case``) can only end in pending_review, escalated or processing_failed.
- Every state change and its audit events are written in ONE transaction.
- The slow model call happens OUTSIDE any database transaction, and the status is re-checked
  when the result is saved, so two simultaneous /process calls cannot both win.
- Refused operations (bad transitions, missing notes) are themselves audited.
"""

import json
import logging
import sqlite3
import uuid
from typing import Any

from app.ai.client import LLMClient
from app.audit.service import append_event, utc_now
from app.core.enums import ActorType, AIRunStatus, CaseStatus, DecisionKind
from app.core.errors import (
    AppError,
    IdempotencyConflictError,
    InvalidTransitionError,
    NotFoundError,
)
from app.core.hashing import canonical_json, sha256_text
from app.core.workflow import (
    PROCESSABLE,
    assert_transition,
    check_can_approve,
    check_can_reject,
    check_can_resolve,
)
from app.db.database import Database, write_tx
from app.retrieval.retriever import Retriever
from app.services.pipeline import PipelineConfig, PipelineResult, run_pipeline

logger = logging.getLogger(__name__)


def _case_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["consequential"] = bool(data["consequential"])
    data["automation_candidate"] = bool(data["automation_candidate"])
    data["decision_codes"] = json.loads(data["decision_codes"] or "[]")
    data.pop("request_hash", None)
    data.pop("idempotency_key", None)
    return data


def _run_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["analysis"] = json.loads(data.pop("analysis_json")) if data["analysis_json"] else None
    for key in ("cited_valid", "cited_invalid", "retrieved_sources"):
        data[key] = json.loads(data[key] or "[]")
    data["grounded"] = bool(data["grounded"])
    return data


class CaseService:
    def __init__(
        self,
        db: Database,
        retriever: Retriever,
        llm: LLMClient,
        pipeline_config: PipelineConfig,
    ) -> None:
        self.db = db
        self.retriever = retriever
        self.llm = llm
        self.config = pipeline_config

    # ------------------------------------------------------------------ create
    def create_case(
        self,
        *,
        message: str,
        customer_ref: str | None,
        idempotency_key: str | None,
        correlation_id: str | None,
    ) -> tuple[dict[str, Any], bool]:
        """Returns (case, created). ``created`` is False when an idempotent replay matched."""
        message = message.strip()
        request_hash = sha256_text(canonical_json({"message": message, "ref": customer_ref}))
        with self.db.session() as conn:
            if idempotency_key:
                existing = self._by_idempotency_key(conn, idempotency_key, request_hash)
                if existing:
                    return existing, False
            case_id = "case_" + uuid.uuid4().hex[:12]
            now = utc_now()
            try:
                with write_tx(conn):
                    conn.execute(
                        "INSERT INTO cases (id, created_at, updated_at, status, message,"
                        " customer_ref, idempotency_key, request_hash)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            case_id,
                            now,
                            now,
                            CaseStatus.NEW.value,
                            message,
                            customer_ref,
                            idempotency_key,
                            request_hash,
                        ),
                    )
                    append_event(
                        conn,
                        case_id=case_id,
                        event_type="case.created",
                        actor_type=ActorType.SYSTEM,
                        outcome="success",
                        correlation_id=correlation_id,
                        input_hash=sha256_text(message),
                        details={"message_length": len(message)},
                    )
            except sqlite3.IntegrityError:
                # Two identical requests raced; the other one won. Return its case.
                if idempotency_key:
                    existing = self._by_idempotency_key(conn, idempotency_key, request_hash)
                    if existing:
                        return existing, False
                raise
            logger.info("case created", extra={"case_id": case_id, "correlation_id": correlation_id})
            return self._get(conn, case_id), True

    @staticmethod
    def _by_idempotency_key(
        conn: sqlite3.Connection, key: str, request_hash: str
    ) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM cases WHERE idempotency_key = ?", (key,)).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise IdempotencyConflictError(
                "This Idempotency-Key was already used with a different request body."
            )
        return _case_dict(row)

    # ------------------------------------------------------------------- reads
    @staticmethod
    def _get(conn: sqlite3.Connection, case_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"Case '{case_id}' was not found.")
        return _case_dict(row)

    def get_case(self, case_id: str) -> dict[str, Any]:
        with self.db.session() as conn:
            return self._get(conn, case_id)

    def list_cases(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        priority: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        for column, value in (("status", status), ("category", category), ("priority", priority)):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM cases {where} ORDER BY created_at DESC, id LIMIT ? OFFSET ?"
        with self.db.session() as conn:
            rows = conn.execute(sql, (*params, limit, offset)).fetchall()
        return [_case_dict(row) for row in rows]

    def get_recommendation(self, case_id: str) -> dict[str, Any]:
        with self.db.session() as conn:
            case = self._get(conn, case_id)
            run = conn.execute(
                "SELECT * FROM ai_runs WHERE case_id = ? ORDER BY id DESC LIMIT 1", (case_id,)
            ).fetchone()
        if run is None:
            raise NotFoundError("This case has not been processed yet.")
        return {"case_id": case_id, "case_status": case["status"], "run": _run_dict(run), "case": case}

    # ----------------------------------------------------------------- process
    def process_case(self, case_id: str, *, correlation_id: str | None) -> dict[str, Any]:
        with self.db.session() as conn:
            case = self._get(conn, case_id)
        current = CaseStatus(case["status"])
        if current not in PROCESSABLE:
            error = InvalidTransitionError(
                f"A case in status '{current.value}' cannot be processed.",
                details={"current": current.value, "allowed_from": sorted(s.value for s in PROCESSABLE)},
            )
            self._audit_denied(case_id, "process", current, error, correlation_id)
            raise error

        # The model call can take a long time, so no transaction is open here.
        result = run_pipeline(
            case["message"], retriever=self.retriever, client=self.llm, config=self.config
        )
        self._save_processing(case_id, current, case["message"], result, correlation_id)
        return self.get_recommendation(case_id)

    def _save_processing(
        self,
        case_id: str,
        original: CaseStatus,
        message: str,
        result: PipelineResult,
        correlation_id: str | None,
    ) -> None:
        outcome, decision = result.outcome, result.decision
        target = decision.status
        assert_transition(original, target)  # programming-error guard
        analysis_json = (
            canonical_json(outcome.analysis.model_dump(mode="json")) if outcome.analysis else None
        )
        with self.db.session() as conn, write_tx(conn):
            updated = conn.execute(
                "UPDATE cases SET status = ?, updated_at = ?, category = ?, priority = ?,"
                " consequential = ?, automation_candidate = ?, decision_codes = ?"
                " WHERE id = ? AND status = ?",
                (
                    target.value,
                    utc_now(),
                    outcome.analysis.category.value if outcome.analysis else None,
                    decision.priority.value,
                    int(decision.consequential),
                    int(decision.automation_candidate),
                    json.dumps(list(decision.reasons)),
                    case_id,
                    original.value,
                ),
            ).rowcount
            if updated == 0:
                raise InvalidTransitionError(
                    "The case changed while it was being processed (another request won)."
                )
            conn.execute(
                "INSERT INTO ai_runs (case_id, created_at, status, model, prompt_version,"
                " attempts, latency_ms, error_category, error_detail, analysis_json,"
                " cited_valid, cited_invalid, grounded, retrieved_sources, output_hash,"
                " correlation_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    case_id,
                    utc_now(),
                    (AIRunStatus.SUCCESS if outcome.ok else AIRunStatus.FAILED).value,
                    outcome.model,
                    outcome.prompt_version,
                    outcome.attempts,
                    outcome.latency_ms,
                    outcome.error_category,
                    outcome.error_detail,
                    analysis_json,
                    json.dumps(outcome.valid_citations),
                    json.dumps(outcome.invalid_citations),
                    int(outcome.grounded),
                    json.dumps([p.source_id for p in result.passages]),
                    outcome.output_hash,
                    correlation_id,
                ),
            )
            append_event(
                conn,
                case_id=case_id,
                event_type="ai.analysis",
                actor_type=ActorType.AI,
                outcome="success" if outcome.ok else "failure",
                correlation_id=correlation_id,
                prompt_version=outcome.prompt_version,
                model=outcome.model,
                input_hash=sha256_text(message),
                output_hash=outcome.output_hash,
                error_category=outcome.error_category,
                details={
                    "attempts": outcome.attempts,
                    "latency_ms": outcome.latency_ms,
                    "retrieved": [p.source_id for p in result.passages],
                    "valid_citations": outcome.valid_citations,
                    "invalid_citations": outcome.invalid_citations,
                    "recommended_action": (
                        outcome.analysis.recommended_action.value if outcome.analysis else None
                    ),
                    "confidence": outcome.analysis.confidence if outcome.analysis else None,
                },
            )
            append_event(
                conn,
                case_id=case_id,
                event_type="rules.decision",
                actor_type=ActorType.SYSTEM,
                outcome="success",
                correlation_id=correlation_id,
                details={
                    "from_status": original.value,
                    "to_status": target.value,
                    "priority": decision.priority.value,
                    "decision_codes": list(decision.reasons),
                    "consequential": decision.consequential,
                    "automation_candidate": decision.automation_candidate,
                },
            )
        logger.info(
            "case processed",
            extra={
                "case_id": case_id,
                "status": target.value,
                "model_ok": outcome.ok,
                "latency_ms": outcome.latency_ms,
                "correlation_id": correlation_id,
            },
        )

    # ------------------------------------------------------------ human actions
    def approve(
        self, case_id: str, *, reviewer: str, note: str | None, correlation_id: str | None
    ) -> dict[str, Any]:
        return self._human_decision(
            case_id,
            reviewer=reviewer,
            note=note,
            correlation_id=correlation_id,
            action="approve",
            target=CaseStatus.APPROVED,
        )

    def reject(
        self, case_id: str, *, reviewer: str, note: str | None, correlation_id: str | None
    ) -> dict[str, Any]:
        return self._human_decision(
            case_id,
            reviewer=reviewer,
            note=note,
            correlation_id=correlation_id,
            action="reject",
            target=CaseStatus.REJECTED,
        )

    def resolve(
        self, case_id: str, *, reviewer: str, note: str | None, correlation_id: str | None
    ) -> dict[str, Any]:
        return self._human_decision(
            case_id,
            reviewer=reviewer,
            note=note,
            correlation_id=correlation_id,
            action="resolve",
            target=CaseStatus.RESOLVED,
        )

    def _human_decision(
        self,
        case_id: str,
        *,
        reviewer: str,
        note: str | None,
        correlation_id: str | None,
        action: str,
        target: CaseStatus,
    ) -> dict[str, Any]:
        with self.db.session() as conn:
            case = self._get(conn, case_id)
        current = CaseStatus(case["status"])
        try:
            if target == CaseStatus.APPROVED:
                clean = check_can_approve(
                    current, consequential=case["consequential"], note=note
                )
            elif target == CaseStatus.REJECTED:
                clean = check_can_reject(current, note=note)
            else:
                clean = check_can_resolve(current, note=note)
        except AppError as error:
            self._audit_denied(case_id, action, current, error, correlation_id, reviewer)
            raise

        with self.db.session() as conn, write_tx(conn):
            updated = conn.execute(
                "UPDATE cases SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (target.value, utc_now(), case_id, current.value),
            ).rowcount
            if updated == 0:
                raise InvalidTransitionError("The case changed while this request was running.")
            if target in (CaseStatus.APPROVED, CaseStatus.REJECTED):
                decision = (
                    DecisionKind.APPROVED if target == CaseStatus.APPROVED else DecisionKind.REJECTED
                )
                conn.execute(
                    "INSERT INTO approvals (case_id, decision, reviewer, note, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (case_id, decision.value, reviewer, clean, utc_now()),
                )
            append_event(
                conn,
                case_id=case_id,
                event_type=f"human.{action}",
                actor_type=ActorType.HUMAN,
                outcome="success",
                correlation_id=correlation_id,
                approval_status=target.value
                if target in (CaseStatus.APPROVED, CaseStatus.REJECTED)
                else None,
                details={
                    "from_status": current.value,
                    "to_status": target.value,
                    "reviewer": reviewer,
                    "note_length": len(clean or ""),
                },
            )
        logger.info(
            "human decision",
            extra={"case_id": case_id, "action": action, "correlation_id": correlation_id},
        )
        return self.get_case(case_id)

    def _audit_denied(
        self,
        case_id: str,
        action: str,
        current: CaseStatus,
        error: AppError,
        correlation_id: str | None,
        reviewer: str | None = None,
    ) -> None:
        with self.db.session() as conn, write_tx(conn):
            append_event(
                conn,
                case_id=case_id,
                event_type="request.denied",
                actor_type=ActorType.HUMAN if reviewer else ActorType.SYSTEM,
                outcome="denied",
                correlation_id=correlation_id,
                error_category=error.code,
                details={
                    "action": action,
                    "current_status": current.value,
                    **({"reviewer": reviewer} if reviewer else {}),
                },
            )

    # ----------------------------------------------------------------- metrics
    def metrics(self) -> dict[str, Any]:
        with self.db.session() as conn:

            def group(column: str) -> dict[str, int]:
                rows = conn.execute(
                    f"SELECT {column} AS k, COUNT(*) AS n FROM cases"
                    f" WHERE {column} IS NOT NULL GROUP BY {column}"
                ).fetchall()
                return {row["k"]: row["n"] for row in rows}

            total = conn.execute("SELECT COUNT(*) AS n FROM cases").fetchone()["n"]
            by_status = group("status")
            by_category = group("category")
            by_priority = group("priority")
            runs = conn.execute(
                "SELECT COUNT(*) AS n,"
                " SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,"
                " AVG(latency_ms) AS avg_latency FROM ai_runs"
            ).fetchone()
            events = conn.execute("SELECT COUNT(*) AS n FROM audit_events").fetchone()["n"]
            latest_eval = conn.execute(
                "SELECT id, created_at, model, dataset_size, metrics_json FROM eval_runs"
                " ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return {
            "total_cases": total,
            "by_status": by_status,
            "by_category": by_category,
            "by_priority": by_priority,
            "pending_approvals": by_status.get(CaseStatus.PENDING_REVIEW.value, 0),
            "ai_runs_total": runs["n"],
            "ai_runs_failed": runs["failed"] or 0,
            "ai_avg_latency_ms": round(runs["avg_latency"], 1) if runs["avg_latency"] else None,
            "audit_events": events,
            "latest_evaluation": (
                {
                    "id": latest_eval["id"],
                    "created_at": latest_eval["created_at"],
                    "model": latest_eval["model"],
                    "dataset_size": latest_eval["dataset_size"],
                    "headline": _headline(json.loads(latest_eval["metrics_json"])),
                }
                if latest_eval
                else None
            ),
        }


def _headline(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "category_accuracy",
        "priority_accuracy",
        "escalation_accuracy",
        "structured_output_validity",
        "model_failure_rate",
    )
    return {key: metrics.get(key) for key in keys}
