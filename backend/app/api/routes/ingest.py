"""Ingestion endpoints.

Uploading a document is how the graph grows beyond the seeded dataset: the file
is converted to Markdown, a model extracts entities and relationships, and
everything is validated against the schema before it is written.

Both entry points do the same work - a file, or pasted text - so the UI can
offer whichever suits the user without a second code path.

Ingestion is slow for a reason the caller cannot see: conversion is local, but
extraction is a model call that can take minutes. So an upload is **queued**
rather than held open - `POST` returns 202 with a poll URL, the work runs in a
background thread, and `GET /{job_id}/status` reports each phase as it finishes.
`?wait=true` blocks and returns the whole report instead, which is what scripts
and the tests use.

Nothing blocking may run on the event loop here. The pipeline is synchronous, so
it goes through a worker thread in both the queued and the waiting path; left
inline it freezes every other request in the process for as long as the model
takes, which is exactly what it used to do.
"""

from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_repository
from app.config import get_settings
from app.graph.client import GraphUnavailable
from app.graph.repository import GraphRepository
from app.ingest import MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS, UnsupportedDocument
from app.ingest import jobs as ingest_jobs
from app.ingest.service import (
    SOURCE_TYPES,
    ingest_document,
    preview_title,
)
from app.llm import resolve_provider
from app.models.ingest import (
    IngestAccepted,
    IngestCapabilities,
    IngestReport,
    IngestStatus,
    IngestTextRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


@router.get("/capabilities", response_model=IngestCapabilities)
def capabilities() -> IngestCapabilities:
    """What this deployment can accept, and whether a model is available.

    The UI asks before offering an upload, so the user is told when extraction
    will not use a model instead of discovering it in the result.
    """
    settings = get_settings()
    return IngestCapabilities(
        supported_extensions=sorted(SUPPORTED_EXTENSIONS),
        max_upload_bytes=MAX_UPLOAD_BYTES,
        source_types=sorted(SOURCE_TYPES),
        model_available=bool(settings.llm_enabled and resolve_provider(settings)),
    )


@router.get("/{job_id}/status", response_model=IngestStatus)
def ingest_status(job_id: str) -> IngestStatus:
    """Progress and result for a queued ingestion.

    A job that is not found is a 404 rather than an empty body, because a lost
    job (a restart) and a job that never started are different problems.
    """
    job = ingest_jobs.registry.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No ingestion job {job_id}. It may have been lost to a restart.",
        )
    return IngestStatus(**job.to_status())


@router.post(
    "/text",
    response_model=IngestReport,
    responses={202: {"model": IngestAccepted}},
)
async def ingest_text(
    payload: IngestTextRequest,
    background_tasks: BackgroundTasks,
    wait: bool = Query(
        default=False,
        description="Block until the document is ingested and return the full report.",
    ),
    repo: GraphRepository = Depends(get_repository),
) -> Response:
    """Ingest pasted text. Same pipeline as a file, without conversion."""
    kwargs = {
        "filename": "",
        "data": None,
        "text": payload.content,
        "title": payload.title,
        "source_type": payload.source_type,
        "source_uri": payload.source_uri,
    }
    return await _dispatch(
        background_tasks=background_tasks,
        repo=repo,
        wait=wait,
        title=preview_title(title=payload.title, text=payload.content),
        kwargs=kwargs,
    )


@router.post(
    "/file",
    response_model=IngestReport,
    responses={202: {"model": IngestAccepted}},
)
async def ingest_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: str = Form(""),
    source_type: str = Form("upload"),
    source_uri: str = Form(""),
    wait: bool = Query(
        default=False,
        description="Block until the document is ingested and return the full report.",
    ),
    repo: GraphRepository = Depends(get_repository),
) -> Response:
    """Ingest an uploaded file, converted to Markdown with MarkItDown.

    The bytes are read before the response is sent, because the upload is closed
    once it is: the queued job carries the content, not the request.
    """
    # Rejected before reading the body, so an oversized upload is refused rather
    # than pulled into memory in full and then refused.
    if file.size is not None and file.size > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                f"That file is {file.size:,} bytes, larger than the "
                f"{MAX_UPLOAD_BYTES:,} byte limit."
            ),
        )

    data = await file.read()
    return await _dispatch(
        background_tasks=background_tasks,
        repo=repo,
        wait=wait,
        title=preview_title(title=title, filename=file.filename or ""),
        kwargs={
            "filename": file.filename or "upload.txt",
            "data": data,
            "text": None,
            "title": title,
            "source_type": source_type,
            "source_uri": source_uri,
        },
    )


async def _dispatch(
    *,
    background_tasks: BackgroundTasks,
    repo: GraphRepository,
    wait: bool,
    title: str,
    kwargs: dict[str, object],
) -> Response:
    """Queue the ingestion, or run it now when the caller asked to wait."""
    if wait:
        report = await run_in_threadpool(_run, repository=repo, **kwargs)
        return JSONResponse(
            status_code=status.HTTP_200_OK, content=jsonable_encoder(report)
        )

    job = ingest_jobs.registry.create(title)
    # A sync callable runs in Starlette's threadpool after the response is sent,
    # so the blocking pipeline never occupies the event loop.
    background_tasks.add_task(
        ingest_jobs.run_ingest_job, job, repo, **kwargs
    )
    accepted = IngestAccepted(
        job_id=job.job_id,
        poll_url=f"/api/ingest/{job.job_id}/status",
        title=job.title,
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED, content=accepted.model_dump()
    )


def _run(*, repository: GraphRepository, **kwargs: object) -> IngestReport:
    """The pipeline, with its failures mapped to HTTP.

    A conversion refusal is the caller's problem, so it becomes a 400 with a
    readable message; a graph outage is ours, so it becomes a 503. Neither should
    surface as a stack trace. The queued path catches the same exceptions in
    `run_ingest_job` and reports them as a failed job instead.
    """
    try:
        return ingest_document(repository=repository, **kwargs)
    except UnsupportedDocument as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except GraphUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
