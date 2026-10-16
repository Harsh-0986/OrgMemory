"""Investigation endpoints.

Route ordering matters: `/history` is declared before `/{investigation_id}` so
FastAPI matches the literal path rather than treating "history" as an id.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.agent import jobs
from app.agent.graph import run_investigation, summarise_state
from app.api.deps import get_repository
from app.graph.repository import GraphRepository
from app.models.api import (
    InvestigationAccepted,
    InvestigationDetailResponse,
    InvestigationHistoryResponse,
    InvestigationRequest,
    InvestigationResponse,
    InvestigationStatus,
    InvestigationSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/investigations", tags=["investigations"])


@router.post(
    "",
    summary="Start a natural-language investigation",
    responses={
        202: {"model": InvestigationAccepted},
        200: {"model": InvestigationResponse, "description": "Returned with wait=true"},
        503: {"description": "Graph or LLM unavailable"},
    },
)
def create_investigation(
    payload: InvestigationRequest,
    background_tasks: BackgroundTasks,
    wait: bool = Query(
        default=False,
        description="Block until the investigation finishes and return the full result.",
    ),
    repo: GraphRepository = Depends(get_repository),
) -> Response:
    """Investigate a question against the knowledge graph.

    Returns immediately with an id and a `running` status; poll
    `GET /api/investigations/{id}` for the result. A real run takes several
    seconds of graph round trips and model calls, so holding the connection open
    would give the client no progress and invites proxy timeouts.

    Pass `wait=true` to block and get the whole answer in one response, which is
    what the tests and scripts use.
    """
    if not wait:
        investigation_id = uuid.uuid4().hex[:12]
        job = jobs.registry.create(f"inv-{investigation_id}", payload.question)
        # A sync callable runs in Starlette's threadpool after the response is
        # sent, so the blocking agent work never occupies the event loop.
        background_tasks.add_task(jobs.run_job, job, repo)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=InvestigationAccepted(
                investigation_id=job.investigation_id,
                question=job.question,
                status=jobs.PENDING,
                poll_url=f"/api/investigations/{job.investigation_id}",
            ).model_dump(),
        )

    state = run_investigation(payload.question, repository=repo)
    summary = summarise_state(state)

    if state.get("status") == "failed" and not summary.get("answer"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=state.get("error") or "Investigation failed without producing an answer",
        )

    return JSONResponse(status_code=200, content=jsonable_encoder(InvestigationResponse(**summary)))


@router.get(
    "/{investigation_id}/status",
    response_model=InvestigationStatus,
    summary="Poll an in-flight investigation",
    responses={404: {"description": "No such job in this process"}},
)
def investigation_status(
    investigation_id: str,
    repo: GraphRepository = Depends(get_repository),
) -> InvestigationStatus:
    """Progress for a running investigation.

    Falls back to the stored record once the job has finished, so a client that
    misses the live job still gets the answer after a restart.
    """
    job = jobs.registry.get(investigation_id)
    if job is not None:
        payload = job.to_status()
        payload["done"] = job.status in jobs.TERMINAL
        if job.status == jobs.COMPLETED and job.result:
            payload["result"] = job.result
        elif job.status in jobs.TERMINAL:
            # Read the persisted record so a finished job survives a restart.
            payload["result"] = repo.get_investigation(investigation_id)
        return InvestigationStatus(**payload)

    record = repo.get_investigation(investigation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No running job or stored investigation with id '{investigation_id}'",
        )
    return InvestigationStatus(
        investigation_id=investigation_id,
        question=record.get("question", ""),
        status=record.get("status", jobs.COMPLETED),
        created_at=record.get("created_at"),
        finished_at=record.get("created_at"),
        steps=[],
        done=True,
        result=record,
    )


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