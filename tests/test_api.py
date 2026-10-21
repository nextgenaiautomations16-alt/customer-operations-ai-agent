"""HTTP-level tests. They need FastAPI; they are skipped automatically if it is not installed.

Run them with:  pytest tests/test_api.py
"""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from app.ai.fakes import AlwaysFailingLLM, HeuristicLLM, ScriptedLLM  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.conftest import EXPORT_MESSAGE, REFUND_MESSAGE, SCENARIO_MESSAGE, make_reply  # noqa: E402

KEY = {"X-API-Key": "test-key"}


def build_client(tmp_path, llm, retriever, **settings):
    base = {
        "database_url": f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
        "staff_api_key": "test-key",
        "llm_max_retries": 1,
        "llm_retry_backoff_seconds": 0.0,
    }
    base.update(settings)
    app = create_app(settings=Settings(**base), llm_client=llm, retriever=retriever)
    return TestClient(app)


@pytest.fixture()
def client(tmp_path, retriever):
    reply = make_reply(category="other", cited_sources=["POL-GEN-002"])
    return build_client(tmp_path, ScriptedLLM([reply]), retriever)


def create(client, message=EXPORT_MESSAGE, **headers):
    response = client.post("/cases", json={"message": message}, headers=headers)
    assert response.status_code in (200, 201), response.text
    return response.json()


# ----------------------------------------------------------------------------- basics
def test_health_is_public_and_reports_state(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["database"] == "ok"
    assert body["knowledge_base_passages"] > 0
    assert "model_reachable" not in body
    assert client.get("/health?deep=true").json()["model_reachable"] is True


def test_openapi_docs_are_available(client):
    assert client.get("/openapi.json").status_code == 200
    assert client.get("/docs").status_code == 200


def test_correlation_id_is_generated_and_echoed(client):
    assert len(client.get("/health").headers["X-Correlation-ID"]) >= 8
    echoed = client.get("/health", headers={"X-Correlation-ID": "my-trace-12345"})
    assert echoed.headers["X-Correlation-ID"] == "my-trace-12345"


# ----------------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "payload",
    [{}, {"message": ""}, {"message": "  "}, {"message": "x" * 4001},
     {"message": "hello there", "customer_ref": "has spaces and @"}],
)
def test_invalid_case_bodies_get_a_consistent_422(client, payload):
    response = client.post("/cases", json=payload)
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error" and error["correlation_id"]


def test_unknown_route_uses_the_same_error_envelope(client):
    response = client.get("/no/such/route")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "http_404"


def test_unknown_case_is_a_consistent_404(client):
    response = client.get("/cases/case_nope", headers=KEY)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# -------------------------------------------------------------------- access control
@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/cases"), ("get", "/metrics"), ("get", "/audit/verify"),
     ("post", "/cases/case_x/process"), ("get", "/evaluations/latest")],
)
def test_staff_endpoints_reject_missing_and_wrong_keys(client, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert getattr(client, method)(path, headers={"X-API-Key": "wrong"}).status_code == 401


def test_staff_endpoints_are_disabled_when_no_key_is_configured(tmp_path, retriever):
    unconfigured = build_client(tmp_path, ScriptedLLM([make_reply()]), retriever, staff_api_key="")
    response = unconfigured.get("/cases", headers=KEY)
    assert response.status_code == 503 and response.json()["error"]["code"] == "not_configured"


# --------------------------------------------------------------------------- workflow
def test_full_lifecycle_over_http(client):
    case = create(client)
    assert case["status"] == "new"
    case_id = case["id"]

    processed = client.post(f"/cases/{case_id}/process", headers=KEY)
    assert processed.status_code == 200
    assert processed.json()["case_status"] == "pending_review"

    rec = client.get(f"/cases/{case_id}/recommendation", headers=KEY).json()
    assert rec["run"]["analysis"]["recommended_action"] == "reply_with_policy_info"
    assert rec["run"]["cited_valid"] == ["POL-GEN-002"]

    approved = client.post(f"/cases/{case_id}/approve", headers=KEY, json={"reviewer": "alice"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    resolved = client.post(
        f"/cases/{case_id}/resolve", headers=KEY, json={"reviewer": "alice", "note": "Sent the export steps"}
    )
    assert resolved.json()["status"] == "resolved"

    audit = client.get(f"/cases/{case_id}/audit", headers=KEY).json()
    assert [e["event_type"] for e in audit["events"]] == [
        "case.created", "ai.analysis", "rules.decision", "human.approve", "human.resolve"
    ]
    assert client.get("/audit/verify", headers=KEY).json()["valid"] is True
    assert client.get("/cases?status=resolved", headers=KEY).json()[0]["id"] == case_id


def test_invalid_transition_is_409_and_audited(client):
    case_id = create(client)["id"]
    response = client.post(f"/cases/{case_id}/approve", headers=KEY, json={"reviewer": "alice", "note": "a fine note"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_transition"
    events = client.get(f"/cases/{case_id}/audit", headers=KEY).json()["events"]
    assert events[-1]["event_type"] == "request.denied"


def test_consequential_approval_without_note_is_422(tmp_path, retriever):
    reply = make_reply(recommended_action="refund_review", cited_sources=["POL-BILL-001"])
    client = build_client(tmp_path, ScriptedLLM([reply]), retriever)
    case_id = create(client, REFUND_MESSAGE)["id"]
    client.post(f"/cases/{case_id}/process", headers=KEY)
    response = client.post(f"/cases/{case_id}/approve", headers=KEY, json={"reviewer": "alice"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "note_required"


def test_reviewer_is_required_for_human_actions(client):
    case_id = create(client)["id"]
    client.post(f"/cases/{case_id}/process", headers=KEY)
    assert client.post(f"/cases/{case_id}/approve", headers=KEY, json={}).status_code == 422


def test_idempotent_create_replays_instead_of_duplicating(client):
    first = client.post("/cases", json={"message": EXPORT_MESSAGE}, headers={"Idempotency-Key": "abc-123"})
    again = client.post("/cases", json={"message": EXPORT_MESSAGE}, headers={"Idempotency-Key": "abc-123"})
    assert (first.status_code, again.status_code) == (201, 200)
    assert first.json()["id"] == again.json()["id"]
    clash = client.post("/cases", json={"message": "different text"}, headers={"Idempotency-Key": "abc-123"})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "idempotency_conflict"
    assert len(client.get("/cases", headers=KEY).json()) == 1


def test_unavailable_model_returns_a_usable_result_not_a_500(tmp_path, retriever):
    client = build_client(tmp_path, AlwaysFailingLLM(), retriever)
    case_id = create(client)["id"]
    response = client.post(f"/cases/{case_id}/process", headers=KEY)
    assert response.status_code == 200
    assert response.json()["case_status"] == "processing_failed"
    assert response.json()["run"]["error_category"] == "unavailable"


def test_brief_scenario_over_http_is_high_priority_and_escalated(tmp_path, retriever):
    reply = make_reply(recommended_action="refund_review", prior_contacts=2,
                       cited_sources=["POL-BILL-001"], urgency="high")
    client = build_client(tmp_path, ScriptedLLM([reply]), retriever)
    case_id = create(client, SCENARIO_MESSAGE)["id"]
    body = client.post(f"/cases/{case_id}/process", headers=KEY).json()
    assert body["case_status"] == "escalated" and body["case"]["priority"] == "high"


# --------------------------------------------------------------- metrics / evaluation
def test_metrics_endpoint(client):
    case_id = create(client)["id"]
    client.post(f"/cases/{case_id}/process", headers=KEY)
    metrics = client.get("/metrics", headers=KEY).json()
    assert metrics["total_cases"] == 1 and metrics["pending_approvals"] == 1
    assert metrics["latest_evaluation"] is None


def test_evaluation_endpoints(tmp_path, retriever):
    client = build_client(tmp_path, HeuristicLLM(), retriever)
    assert client.get("/evaluations/latest", headers=KEY).status_code == 404
    run = client.post("/evaluations/run", headers=KEY, json={"limit": 5})
    assert run.status_code == 200 and run.json()["dataset_size"] == 5
    latest = client.get("/evaluations/latest", headers=KEY).json()
    assert latest["model"] == "fake-heuristic" and latest["metrics"]["dataset_size"] == 5
    assert client.get("/metrics", headers=KEY).json()["latest_evaluation"]["dataset_size"] == 5
