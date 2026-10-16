"""Ingestion endpoints.

Uploading a document is how the graph grows beyond the seeded dataset: the file
is converted to Markdown, a model extracts entities and relationships, and
everything is validated against the schema before it is written.

Both entry points do the same work - a file, or pasted text - so the UI can
offer whichever suits the user without a second code path.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.api.deps import get_repository
from app.config import get_settings
from app.graph.client import GraphUnavailable
from app.graph.repository import GraphRepository
from app.ingest import MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS, UnsupportedDocument
from app.ingest.service import SOURCE_TYPES, ingest_document
from app.llm import resolve_provider
from app.models.ingest import IngestCapabilities, IngestReport, IngestTextRequest

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


@router.post("/text", response_model=IngestReport)
def ingest_text(
    payload: IngestTextRequest,
    repo: GraphRepository = Depends(get_repository),
) -> IngestReport:
    """Ingest pasted text. Same pipeline as a file, without conversion."""
    return _run(
        repository=repo,
        filename="",
        data=None,
        text=payload.content,
        title=payload.title,
        source_type=payload.source_type,
        source_uri=payload.source_uri,
    )


@router.post("/file", response_model=IngestReport, status_code=status.HTTP_200_OK)
async def ingest_file(
    file: UploadFile = File(...),
    title: str = Form(""),
    source_type: str = Form("upload"),
    source_uri: str = Form(""),
    repo: GraphRepository = Depends(get_repository),
) -> IngestReport:
    """Ingest an uploaded file, converted to Markdown with MarkItDown."""
    data = await file.read()
    return _run(
        repository=repo,
        filename=file.filename or "upload.txt",
        data=data,
        text=None,
        title=title,
        source_type=source_type,
        source_uri=source_uri,
    )


def _run(
    *,
    repository: GraphRepository,
    filename: str,
    data: bytes | None,
    text: str | None,
    title: str,
    source_type: str,
    source_uri: str,
) -> IngestReport:
    """Shared path for both entry points, with errors mapped to HTTP.

    A conversion failure is the user's problem, so it becomes a 400 with a
    readable message; a graph failure is ours, so it becomes a 503. Neither
    should surface as a stack trace.
    """
    try:
        return ingest_document(
            repository=repository,
            filename=filename,
            data=data,
            text=text,
            title=title,
            source_type=source_type,
            source_uri=source_uri,
        )
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
