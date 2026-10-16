"""Request and response models for document ingestion."""

from __future__ import annotations

from pydantic import BaseModel, Field


class IngestedEntity(BaseModel):
    """One entity an upload created or pointed at."""

    id: str
    type: str
    name: str


class RejectedItem(BaseModel):
    """Something the extractor proposed that we refused to write, and why.

    Defined here rather than next to the extractor so the API contract does not
    depend on the ingestion implementation.
    """

    item: str
    reason: str


class IngestReport(BaseModel):
    """What an upload actually did.

    The split between `entities_created` and `entities_linked` is deliberate:
    "the graph learned something new" and "the graph already knew this" are
    different outcomes, and collapsing them would overstate what the document
    contributed.
    """

    document_id: str
    title: str
    source_type: str
    #: False when no model was configured. An empty extraction and an absent
    #: model are otherwise indistinguishable, and they mean different things.
    model_used: bool
    summary: str = ""
    #: Why extraction did not happen, when a call was attempted and failed.
    #: Empty when no model is configured: that is a setting, not an error, and
    #: the two must not read the same in the UI.
    model_error: str | None = None
    entities_created: list[IngestedEntity] = Field(default_factory=list)
    #: Entities the document referred to that were already in the graph.
    entities_linked: list[IngestedEntity] = Field(default_factory=list)
    relationships_created: list[str] = Field(default_factory=list)
    #: Proposals the validator refused, each with the reason. Reported rather
    #: than dropped, so a model misreading is visible instead of silent.
    rejected: list[RejectedItem] = Field(default_factory=list)
    citations_linked: int = 0
    truncated: bool = False
    markdown_chars: int = 0


class IngestTextRequest(BaseModel):
    """Pasted text, the non-file path into ingestion."""

    title: str = Field(default="", max_length=300)
    content: str = Field(min_length=1)
    source_type: str = "note"
    source_uri: str = ""


class IngestCapabilities(BaseModel):
    """What the UI needs to know to render the upload control honestly."""

    supported_extensions: list[str]
    max_upload_bytes: int
    source_types: list[str]
    #: Whether ingestion will actually use a model right now. The UI says so
    #: before the user uploads, rather than after.
    model_available: bool


class IngestAccepted(BaseModel):
    """Returned immediately (202) when an upload is queued."""

    job_id: str
    poll_url: str
    title: str


class IngestStep(BaseModel):
    """One finished phase of an ingestion, published as it completes.

    Ingestion is slow enough to need progress: conversion is local but extraction
    is a model call. This is what stops the wait from being one opaque spinner.
    """

    phase: str
    title: str
    detail: str = ""
    duration_ms: float = 0.0


class IngestStatus(BaseModel):
    """The state of one ingestion job."""

    job_id: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[IngestStep] = Field(default_factory=list)
    error: str | None = None
    done: bool = False
    #: The report, once the job has settled successfully.
    result: IngestReport | None = None
