"""Graph exploration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_repository
from app.graph.repository import GraphRepository
from app.models.api import GraphOverviewResponse, NeighborhoodResponse

router = APIRouter(prefix="/api/graph", tags=["graph"])


@router.get(
    "/overview",
    response_model=GraphOverviewResponse,
    summary="Counts of every node label and relationship type",
)
def overview(repo: GraphRepository = Depends(get_repository)) -> GraphOverviewResponse:
    """Return the shape of the company graph.

    Used by the dashboard header and as a quick check that seeding succeeded.
    """
    return GraphOverviewResponse(**repo.overview())


@router.get(
    "/neighborhood",
    response_model=NeighborhoodResponse,
    summary="Subgraph around one entity",
)
def neighborhood(
    entity_id: str = Query(description="Exact entity id, e.g. 'svc-checkout'"),
    depth: int | None = Query(
        default=None,
        ge=1,
        le=6,
        description="Traversal depth; clamped to the server-configured maximum.",
    ),
    repo: GraphRepository = Depends(get_repository),
) -> NeighborhoodResponse:
    """Return nodes, edges and paths within `depth` hops of `entity_id`.

    An unknown id returns an empty subgraph rather than a 404, so the frontend
    can render "not found in graph" without special-casing the error.
    """
    result = repo.neighborhood(entity_id, depth)
    return NeighborhoodResponse(**result)