"""FalkorDB connection management.

A single lazily-created client is shared process-wide.  Failure to connect is
surfaced as `GraphUnavailable` so the API can return a structured 503 instead
of a stack trace - a missing graph database should degrade the product
predictably, not crash it.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class GraphUnavailable(RuntimeError):
    """Raised when the graph database cannot be reached or is misconfigured."""


_client: Any | None = None
_graph: Any | None = None


def _build_client(settings: Settings) -> Any:
    """Instantiate the FalkorDB client for the configured endpoint."""
    from falkordb import FalkorDB

    kwargs: dict[str, Any] = {
        "host": settings.falkordb_host,
        "port": settings.falkordb_port,
    }

    # FalkorDB Cloud always authenticates; a bare local instance may not.
    if settings.falkordb_password:
        kwargs["username"] = settings.falkordb_username
        kwargs["password"] = settings.falkordb_password

    if settings.falkordb_tls:
        # FalkorDB Cloud endpoints that terminate TLS use redis' native ssl flag.
        kwargs["ssl"] = True

    try:
        return FalkorDB(**kwargs)
    except TypeError:
        # Older/newer client signatures - retry with the positional form.
        try:
            return FalkorDB(
                settings.falkordb_host,
                settings.falkordb_port,
                settings.falkordb_password,
                username=settings.falkordb_username,
                ssl=settings.falkordb_tls,
            )
        except Exception as exc:  # pragma: no cover - defensive
            raise GraphUnavailable(f"Could not construct FalkorDB client: {exc}") from exc


def get_connection() -> Any:
    """Return the shared FalkorDB client, creating it on first use."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = _build_client(settings)
        logger.info(
            "FalkorDB client created for %s:%s",
            settings.falkordb_host,
            settings.falkordb_port,
        )
    return _client


def get_graph() -> Any:
    """Return the selected graph handle used for every query."""
    global _graph
    if _graph is None:
        settings = get_settings()
        _graph = get_connection().select_graph(settings.falkordb_graph)
        logger.info("Selected FalkorDB graph '%s'", settings.falkordb_graph)
    return _graph


def ping() -> bool:
    """Cheap liveness probe. Never raises - returns False on any failure."""
    try:
        graph = get_graph()
        graph.query("RETURN 1")
        return True
    except Exception as exc:
        logger.warning("FalkorDB ping failed: %s", exc)
        return False


def reset_connection() -> None:
    """Drop the cached client so the next call reconnects.

    Used by tests and by the retry path after a transient network failure.
    """
    global _client, _graph
    _client = None
    _graph = None


def close_connection() -> None:
    """Close the underlying socket pool, if the client exposes one."""
    global _client, _graph
    if _client is not None:
        for attr in ("connection", "_connection"):
            conn = getattr(_client, attr, None)
            closer = getattr(conn, "disconnect", None)
            if callable(closer):
                try:
                    closer()
                except Exception:  # pragma: no cover - best effort
                    logger.debug("Error while closing FalkorDB connection", exc_info=True)
    reset_connection()