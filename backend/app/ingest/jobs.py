"""Async ingestion jobs.

Uploading a document is slow for a reason the caller cannot see: conversion is
local, but extraction is a model call that can take minutes on a loaded provider.
Holding the HTTP connection open for it gives one opaque spinner, and it used to
be worse than that - the blocking pipeline ran on the event loop and froze every
other request in the process until the model answered.

So an upload is queued instead: `POST` returns immediately with an id, the work
runs in a background thread, and the client polls for progress. The phases
(`convert`, `extract`, `write`) are published as they complete, so the wait shows
what is actually happening rather than merely that something is.

This mirrors `app.agent.jobs`, which does the same thing for investigations. It
is deliberately a separate registry rather than a shared one: the two jobs carry
different payloads and their status shapes are published API, so folding them
together would mean renaming the investigation fields that already work.
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.ingest.service import ingest_document
from app.models.ingest import IngestStep

logger = logging.getLogger(__name__)

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"

TERMINAL = frozenset({COMPLETED, FAILED})


@dataclass
class IngestJob:
    """One queued or finished ingestion."""

    job_id: str
    title: str
    status: str = PENDING
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_status(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": self.steps,
            "error": self.error,
            "done": self.status in TERMINAL,
            "result": self.result,
        }


class IngestJobRegistry:
    """Thread-safe store of ingestion jobs for this process."""

    def __init__(self) -> None:
        self._jobs: dict[str, IngestJob] = {}
        self._lock = threading.Lock()

    def create(self, title: str) -> IngestJob:
        job = IngestJob(job_id=f"ing-{uuid.uuid4().hex[:12]}", title=title)
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> IngestJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                for key, value in fields.items():
                    setattr(job, key, value)

    def append_step(self, job_id: str, step: IngestStep) -> None:
        """Publish one finished phase.

        Separate from `update` because `get` takes the same non-reentrant lock:
        publishing from inside a `get` would deadlock.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.steps.append(step.model_dump())

    def clear(self) -> int:
        with self._lock:
            count = len(self._jobs)
            self._jobs.clear()
            return count


#: Process-wide, like the investigation registry: a restart loses in-flight jobs,
#: which is the honest outcome rather than a phantom "running" forever.
registry = IngestJobRegistry()


def run_ingest_job(job: IngestJob, repository: Any, **ingest_kwargs: Any) -> None:
    """Run one ingestion synchronously. Called from the background thread pool.

    Never raises: a crashed job must not take the worker with it, and the client
    is polling for an answer either way.
    """
    registry.update(
        job.job_id, status=RUNNING, started_at=datetime.now(UTC).isoformat()
    )
    logger.info("Ingestion %s started: %s", job.job_id, job.title)

    try:
        report = ingest_document(
            repository=repository,
            on_progress=lambda step: registry.append_step(job.job_id, step),
            **ingest_kwargs,
        )
        registry.update(
            job.job_id,
            status=COMPLETED,
            result=report.model_dump(),
            finished_at=datetime.now(UTC).isoformat(),
        )
        logger.info(
            "Ingestion %s finished: %s (%d new entities)",
            job.job_id,
            report.document_id,
            len(report.entities_created),
        )
    except Exception as exc:  # noqa: BLE001 - a job must never kill the worker
        logger.exception("Ingestion %s failed", job.job_id)
        registry.update(
            job.job_id,
            status=FAILED,
            # The message is user-facing: the panel shows it verbatim, so a
            # conversion refusal reads as advice rather than a stack trace.
            error=str(exc) or "The document could not be ingested.",
            finished_at=datetime.now(UTC).isoformat(),
        )
