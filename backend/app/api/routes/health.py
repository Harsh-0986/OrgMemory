"""Health endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.config import get_settings
from app.graph import client as graph_client
from app.llm import llm_is_configured
from app.models.api import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Service health")
def health() -> HealthResponse:
    """Report process health plus graph and LLM reachability.

    Never raises: an unreachable graph yields `degraded` with HTTP 200 so that
    container orchestrators do not kill a pod that is merely waiting on
    credentials.
    """
    settings = get_settings()
    connected = graph_client.ping()

    return HealthResponse(
        status="ok" if connected else "degraded",
        app=settings.app_name,
        environment=settings.environment,
        graph_connected=connected,
        graph_name=settings.falkordb_graph,
        llm_configured=llm_is_configured(),
        version=__version__,
        missing_settings=settings.missing_settings,
    )