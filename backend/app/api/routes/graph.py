"""Graph exploration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_repository
from app.graph.repository import GraphRepository
from app.models.api import (
    EntityListResponse,
    EntityRecord,
    FullGraphResponse,
    GraphOverviewResponse,
    NeighborhoodResponse,
)

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
    "/full",
    response_model=FullGraphResponse,
    summary="Every node and edge, for the whole-graph view",
)
def full_graph(
    repo: GraphRepository = Depends(get_repository),
) -> FullGraphResponse:
    """Return the entire graph as nodes and edges.

    Bounded by `GRAPH_MAX_RESULTS`. Edge endpoints that do not resolve to a
    returned node are dropped rather than emitted as dangling references, so the
    renderer never has to guard against them.
    """
    return FullGraphResponse(**repo.full_graph())


@router.get(
    "/entities",
    response_model=EntityListResponse,
    summary="Every entity of one label, for the data browser",
)
def entities(
    label: str = Query(description="Node label, e.g. 'Service'"),
    q: str = Query(default="", description="Optional free-text filter"),
    repo: GraphRepository = Depends(get_repository),
) -> EntityListResponse:
    """List what the graph actually contains for one label.

    This is the "show me what you know" view: every stored entity with its
    full property set, so a reader can check the dataset's scope and quality
    without writing a query themselves.
    """
    try:
        rows = repo.list_entities(label, q)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return EntityListResponse(
        label=label,
        total=len(rows),
        search=q,
        entities=[EntityRecord.model_validate(row) for row in rows],
    )


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