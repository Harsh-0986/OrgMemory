"""Investigation endpoints.

Route ordering matters: `/history` is declared before `/{investigation_id}` so
FastAPI matches the literal path rather than treating "history" as an id.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.agent.graph import run_investigation, summarise_state
from app.api.deps import get_repository
from app.graph.repository import GraphRepository
from app.models.api import (
    InvestigationDetailResponse,
    InvestigationHistoryResponse,
    InvestigationRequest,
    InvestigationResponse,
    InvestigationSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/investigations", tags=["investigations"])


@router.post(
    "",
    response_model=InvestigationResponse,
    summary="Run a natural-language investigation",
    responses={503: {"description": "Graph or LLM unavailable"}},
)
def create_investigation(
    payload: InvestigationRequest,
    repo: GraphRepository = Depends(get_repository),
) -> InvestigationResponse:
    """Investigate a question against the knowledge graph.

    Synchronous by design: the whole workflow is bounded by the agent's step and
    tool-call limits, so it completes in seconds. The result always carries an
    answer plus the evidence behind it, even when the model is unavailable.
    """
    state = run_investigation(payload.question, repository=repo)
    summary = summarise_state(state)

    if state.get("status") == "failed" and not summary.get("answer"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=state.get("error") or "Investigation failed without producing an answer",
        )

    return InvestigationResponse(**summary)


@router.get(
    "/history",
    response_model=InvestigationHistoryResponse,
    summary="Past investigations, newest first",
)
def investigation_history(
    limit: int = Query(default=20, ge=1, le=100),
    repo: GraphRepository = Depends(get_repository),
) -> InvestigationHistoryResponse:
    """List stored investigations.

    Returns an empty list rather than an error when no memory exists yet, which
    is the normal state on a fresh database.
    """
    items = repo.list_investigations(limit=limit)
    return InvestigationHistoryResponse(
        total=len(items),
        investigations=[
            InvestigationSummary(
                id=item["id"],
                question=item.get("question") or "",
                created_at=item.get("created_at"),
                summary=item.get("summary") or "",
                cited_ids=item.get("cited_ids") or [],
            )
            for item in items
        ],
    )


@router.get(
    "/{investigation_id}",
    response_model=InvestigationDetailResponse,
    summary="Retrieve one stored investigation",
    responses={404: {"description": "No such investigation"}},
)
def get_investigation(
    investigation_id: str,
    repo: GraphRepository = Depends(get_repository),
) -> InvestigationDetailResponse:
    """Fetch a stored investigation and the entities it cited.

    This is the cross-session memory: a later request can read an earlier
    investigation and traverse its citations back into the graph.
    """
    record = repo.get_investigation(investigation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No investigation found with id '{investigation_id}'",
        )

    return InvestigationDetailResponse(
        id=record.get("id", investigation_id),
        question=record.get("question", ""),
        answer=record.get("answer", ""),
        summary=record.get("summary", ""),
        status=record.get("status", "completed"),
        created_at=record.get("created_at"),
        cited_ids=record.get("cited_ids") or [],
        cited_entities=record.get("cited_entities") or [],
        metadata=record.get("metadata") or {},
    )