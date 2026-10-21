"""Application factory.

Run with:   uvicorn app.main:create_app --factory --reload
Tests build their own app with fake models: create_app(settings=..., llm_client=FakeLLM()).
"""

import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.ai.client import LLMClient
from app.ai.factory import build_llm_client
from app.api.routes import router
from app.core.config import Settings, sqlite_path
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.db.database import Database
from app.retrieval.retriever import Retriever
from app.services.cases import CaseService
from app.services.pipeline import PipelineConfig

logger = logging.getLogger(__name__)
_ID_OK = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
ROOT = Path(__file__).resolve().parent.parent

DESCRIPTION = """
Triage for incoming customer support messages (**synthetic data only**).

The AI *suggests*; deterministic rules *decide* priority and escalation; a *human* approves or
rejects anything consequential; every step is written to a hash-chained audit log.

Staff endpoints need the `X-API-Key` header (click **Authorize** in this page). This is a
development placeholder, not real authentication.
"""


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _error_response(
    status_code: int, code: str, message: str, details: object, correlation_id: str | None
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "correlation_id": correlation_id,
        }
    }
    return JSONResponse(status_code=status_code, content=body)


def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    retriever: Retriever | None = None,
) -> FastAPI:
    configure_logging()
    settings = settings or Settings.load(ROOT / ".env")

    db_file = sqlite_path(settings.database_url)
    db = Database(db_file if Path(db_file).is_absolute() else ROOT / db_file)
    db.init()

    llm = llm_client or build_llm_client(settings)
    retriever = retriever or Retriever.from_directory(_resolve(settings.knowledge_base_dir))
    pipeline_config = PipelineConfig.from_settings(settings)

    app = FastAPI(
        title="Customer Operations AI Agent",
        version=__version__,
        description=DESCRIPTION,
    )
    app.state.settings = Settings(
        **{**settings.__dict__, "dataset_path": str(_resolve(settings.dataset_path))}
    )
    app.state.db = db
    app.state.llm = llm
    app.state.retriever = retriever
    app.state.pipeline_config = pipeline_config
    app.state.case_service = CaseService(db, retriever, llm, pipeline_config)

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get("x-correlation-id", "")
        correlation_id = incoming if _ID_OK.match(incoming) else uuid.uuid4().hex
        request.state.correlation_id = correlation_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        logger.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "correlation_id": correlation_id,
            },
        )
        return response

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, error: AppError) -> JSONResponse:
        return _error_response(
            error.status_code,
            error.code,
            error.message,
            error.details,
            getattr(request.state, "correlation_id", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, error: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(p) for p in item["loc"] if p != "body"), "problem": item["msg"]}
            for item in error.errors()
        ]
        return _error_response(
            422,
            "validation_error",
            "The request is not valid.",
            problems,
            getattr(request.state, "correlation_id", None),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, error: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            error.status_code,
            f"http_{error.status_code}",
            str(error.detail),
            None,
            getattr(request.state, "correlation_id", None),
        )

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, error: Exception) -> JSONResponse:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.error(
            "unhandled error",
            extra={"error_type": type(error).__name__, "correlation_id": correlation_id},
        )
        return _error_response(
            500, "internal_error", "Something went wrong on our side.", None, correlation_id
        )

    app.include_router(router)
    return app
