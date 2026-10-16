"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.routes import graph, health, ingest, investigations
from app.config import get_settings

logger = logging.getLogger(__name__)

DESCRIPTION = """
OrgMemory is an AI Company Brain backed by a FalkorDB knowledge graph.

It answers questions about an engineering organisation by traversing connected
people, services, projects, incidents, decisions and documents - and cites the
graph records behind every material claim.

**Grounding rules**

* Answers are composed from retrieved evidence, never from free association.
* Claims the graph cannot support are labelled as unknown rather than guessed.
* Incident causes are reported only where a `CAUSED_BY` relationship exists.
* Suggested actions are advisory and require human review.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Log configuration problems at startup instead of failing silently."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    missing = settings.missing_settings
    if missing:
        logger.warning(
            "Starting with incomplete configuration. Missing: %s. "
            "Graph reads will fail until these are set in .env",
            ", ".join(missing),
        )
    else:
        logger.info(
            "Configured: graph=%s@%s, model=%s",
            settings.falkordb_graph,
            settings.falkordb_host,
            settings.nvidia_model,
        )
    yield


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=DESCRIPTION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(graph.router)
    app.include_router(investigations.router)
    app.include_router(ingest.router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        """Point humans at the docs rather than a blank page."""
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()