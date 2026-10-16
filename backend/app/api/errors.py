"""Structured error handling.

Every failure the client can see is rendered as the same JSON envelope:
`{"error": {"code", "message", "detail"}}`.  Graph outages become 503 and LLM
misconfiguration becomes 503 too - both are "the dependency is not ready" - while
genuine bad input stays a 4xx.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.graph.client import GraphUnavailable
from app.llm import LLMUnavailable
from app.models.api import ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

#: Errors returned for each Starlette/FastAPI status code.
_CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "dependency_unavailable",
}


def _envelope(
    code: str, message: str, detail: str | None, http_status: int
) -> JSONResponse:
    """Build the standard error JSON response."""
    body = ErrorResponse(error=ErrorDetail(code=code, message=message, detail=detail))
    return JSONResponse(status_code=http_status, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    """Attach every handler to the application."""

    @app.exception_handler(GraphUnavailable)
    async def _graph_unavailable(request: Request, exc: GraphUnavailable) -> JSONResponse:
        logger.error("Graph unavailable on %s: %s", request.url.path, exc)
        return _envelope(
            "graph_unavailable",
            "The knowledge graph is unavailable. Check FalkorDB credentials and connectivity.",
            str(exc),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.exception_handler(LLMUnavailable)
    async def _llm_unavailable(request: Request, exc: LLMUnavailable) -> JSONResponse:
        logger.error("LLM unavailable on %s: %s", request.url.path, exc)
        return _envelope(
            "llm_unavailable",
            "The language model is unavailable. Set NVIDIA_API_KEY to enable "
            "natural-language investigation.",
            str(exc),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = first.get("msg", "Request validation failed")
        return _envelope(
            "validation_error",
            f"{field}: {message}" if field else message,
            None,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _CODE_BY_STATUS.get(exc.status_code, "http_error")
        detail = exc.detail if isinstance(exc.detail, str) else None
        return _envelope(code, str(exc.detail), detail, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error on %s", request.url.path)
        return _envelope(
            "internal_error",
            "An unexpected error occurred while processing the request.",
            None,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )