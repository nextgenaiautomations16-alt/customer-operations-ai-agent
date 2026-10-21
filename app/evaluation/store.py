"""Save and load evaluation runs in the database."""

import json
from typing import Any

from app.audit.service import utc_now
from app.db.database import Database, write_tx


def save_eval_run(db: Database, result: dict[str, Any]) -> int:
    with db.session() as conn, write_tx(conn):
        cursor = conn.execute(
            "INSERT INTO eval_runs (created_at, model, prompt_version, dataset_version,"
            " dataset_size, metrics_json, failures_json) VALUES (?,?,?,?,?,?,?)",
            (
                utc_now(),
                result["model"],
                result["prompt_version"],
                result["dataset_version"],
                result["dataset_size"],
                json.dumps(result["metrics"]),
                json.dumps(result["failures"]),
            ),
        )
        return int(cursor.lastrowid)


def latest_eval_run(db: Database) -> dict[str, Any] | None:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM eval_runs ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    data = dict(row)
    data["metrics"] = json.loads(data.pop("metrics_json"))
    data["failures"] = json.loads(data.pop("failures_json"))
    return data
