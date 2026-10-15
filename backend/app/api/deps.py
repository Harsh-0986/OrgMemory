"""Shared FastAPI dependencies."""

from __future__ import annotations

from functools import lru_cache

from app.graph.repository import GraphRepository


@lru_cache
def get_repository() -> GraphRepository:
    """One repository instance per process.

    The repository holds no mutable per-request state - all budget tracking
    lives in the toolbox - so a singleton is safe.
    """
    return GraphRepository()


def reset_repository() -> None:
    """Drop the cached repository (used by tests)."""
    get_repository.cache_clear()