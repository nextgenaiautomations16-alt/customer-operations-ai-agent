"""HTTP endpoints. Each handler is thin: validate, call the service, shape the response."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from app import __version__
from app.api.deps import get_correlation_id, get_service, require_staff
from app.audit.service import events_for_case, recent_events, verify_audit_log
from app.core.enums import CaseStatus, Category, Priority
from app.core.errors import AppError, NotFoundError
from app.evaluation.runner import load_dataset, run_evaluation
from app.evaluation.store import latest_eval_run, save_eval_run
from app.schemas.api import (
    CaseCreate,
    CaseOut,
    ErrorResponse,
    EvaluationRequest,
    RecommendationOut,
    ReviewAction,
)
from app.services.cases import CaseService

router = APIRouter()
staff = [Depends(require_staff)]
ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}


@router.get("/health", tags=["system"])
def health(request: Request, deep: bool = Query(default=False)) -> dict[str, Any]:
    """Liveness check. Add ?deep=true to also test that the language model is reachable."""
    state = request.app.state
    with state.db.session() as conn:
        conn.execute("SELECT 1").fetchone()
    body: dict[str, Any] = {
        "status": "ok",
        "version": __version__,
        "database": "ok",
        "knowledge_base_passages": state.retriever.passage_count,
        "model": state.llm.model_name,
        "prompt_version": state.settings.prompt_version,
    }
    if deep:
        body["model_reachable"] = state.llm.ping()
    return body


@router.post(
    "/cases", status_code=201, response_model=CaseOut, tags=["cases"], responses=ERRORS
)
def create_case(
    payload: CaseCreate,
    response: Response,
    service: CaseService = Depends(get_service),
    correlation_id: str | None = Depends(get_correlation_id),
    idempotency_key: str | None = Header(default=None, max_length=128),
) -> dict[str, Any]:
    """Submit a customer message. Send an Idempotency-Key header to make retries safe."""
    case, created = service.create_case(
        message=payload.message,
        customer_ref=payload.customer_ref,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    if not created:
        response.status_code = 200  # same request replayed: return the existing case
    return case


@router.get("/cases", response_model=list[CaseOut], tags=["cases"], dependencies=staff)
def list_cases(
    status: CaseStatus | None = None,
    category: Category | None = None,
    priority: Priority | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: CaseService = Depends(get_service),
) -> list[dict[str, Any]]:
    return service.list_cases(
        status=status.value if status else None,
        category=category.value if category else None,
        priority=priority.value if priority else None,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/cases/{case_id}", response_model=CaseOut, tags=["cases"], dependencies=staff, responses=ERRORS
)
def get_case(case_id: str, service: CaseService = Depends(get_service)) -> dict[str, Any]:
    return service.get_case(case_id)


@router.post(
    "/cases/{case_id}/process",
    response_model=RecommendationOut,
    tags=["workflow"],
    dependencies=staff,
    responses=ERRORS,
)
def process_case(
    case_id: str,
    service: CaseService = Depends(get_service),
    correlation_id: str | None = Depends(get_correlation_id),
) -> dict[str, Any]:
    """Run retrieval + AI analysis + business rules. The AI only suggests; it never approves."""
    return service.process_case(case_id, correlation_id=correlation_id)


@router.get(
    "/cases/{case_id}/recommendation",
    response_model=RecommendationOut,
    tags=["workflow"],
    dependencies=staff,
    responses=ERRORS,
)
def get_recommendation(case_id: str, service: CaseService = Depends(get_service)) -> dict[str, Any]:
    return service.get_recommendation(case_id)


@router.post(
    "/cases/{case_id}/approve", response_model=CaseOut, tags=["human review"],
    dependencies=staff, responses=ERRORS,
)
def approve_case(
    case_id: str,
    payload: ReviewAction,
    service: CaseService = Depends(get_service),
    correlation_id: str | None = Depends(get_correlation_id),
) -> dict[str, Any]:
    """Human approval. Consequential actions (refunds, unlocks) need a note of 10+ characters."""
    return service.approve(
        case_id, reviewer=payload.reviewer, note=payload.note, correlation_id=correlation_id
    )


@router.post(
    "/cases/{case_id}/reject", response_model=CaseOut, tags=["human review"],
    dependencies=staff, responses=ERRORS,
)
def reject_case(
    case_id: str,
    payload: ReviewAction,
    service: CaseService = Depends(get_service),
    correlation_id: str | None = Depends(get_correlation_id),
) -> dict[str, Any]:
    return service.reject(
        case_id, reviewer=payload.reviewer, note=payload.note, correlation_id=correlation_id
    )


@router.post(
    "/cases/{case_id}/resolve", response_model=CaseOut, tags=["human review"],
    dependencies=staff, responses=ERRORS,
)
def resolve_case(
    case_id: str,
    payload: ReviewAction,
    service: CaseService = Depends(get_service),
    correlation_id: str | None = Depends(get_correlation_id),
) -> dict[str, Any]:
    return service.resolve(
        case_id, reviewer=payload.reviewer, note=payload.note, correlation_id=correlation_id
    )


@router.get("/cases/{case_id}/audit", tags=["audit"], dependencies=staff, responses=ERRORS)
def case_audit(case_id: str, request: Request, service: CaseService = Depends(get_service)) -> dict[str, Any]:
    service.get_case(case_id)  # 404 if the case does not exist
    with request.app.state.db.session() as conn:
        events = events_for_case(conn, case_id)
    return {"case_id": case_id, "events": events}


@router.get("/audit/verify", tags=["audit"], dependencies=staff)
def audit_verify(request: Request) -> dict[str, Any]:
    """Re-check the whole audit hash chain. Keep head_hash somewhere else to detect truncation."""
    with request.app.state.db.session() as conn:
        result = verify_audit_log(conn)
    return {
        "valid": result.valid,
        "events_checked": result.events_checked,
        "head_hash": result.head_hash,
        "first_invalid_seq": result.first_invalid_seq,
        "reason": result.reason,
    }


@router.get("/audit/recent", tags=["audit"], dependencies=staff)
def audit_recent(request: Request, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    with request.app.state.db.session() as conn:
        return {"events": recent_events(conn, limit)}


@router.post("/evaluations/run", tags=["evaluation"], dependencies=staff)
def evaluations_run(request: Request, payload: EvaluationRequest | None = None) -> dict[str, Any]:
    """Run the labelled dataset through the pipeline and store the result.

    This blocks until finished. With a real local model a full run can take many minutes;
    prefer `python scripts/run_eval.py`, or pass a small `limit`.
    """
    state = request.app.state
    dataset_path = Path(state.settings.dataset_path)
    if not dataset_path.is_file():
        raise AppError(f"Dataset not found at {dataset_path}")
    dataset = load_dataset(dataset_path)
    result = run_evaluation(
        dataset,
        retriever=state.retriever,
        client=state.llm,
        config=state.pipeline_config,
        limit=payload.limit if payload else None,
    )
    run_id = save_eval_run(state.db, result)
    return {
        "id": run_id,
        "model": result["model"],
        "dataset_size": result["dataset_size"],
        "metrics": result["metrics"],
        "failures": result["failures"],
    }


@router.get("/evaluations/latest", tags=["evaluation"], dependencies=staff, responses=ERRORS)
def evaluations_latest(request: Request) -> dict[str, Any]:
    latest = latest_eval_run(request.app.state.db)
    if latest is None:
        raise NotFoundError("No evaluation has been run yet. POST /evaluations/run first.")
    return latest


@router.get("/metrics", tags=["system"], dependencies=staff)
def metrics(service: CaseService = Depends(get_service)) -> dict[str, Any]:
    """Operational numbers: cases by status/category/priority, pending approvals, AI failures."""
    return service.metrics()

