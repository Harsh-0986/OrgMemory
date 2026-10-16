"""Async investigation jobs.

`POST /api/investigations` returns immediately with an id and a `running` status;
the LangGraph workflow then runs in a background thread and the client polls
`GET /api/investigations/{id}` until it settles.

Two reasons this is worth doing:

* **The work is genuinely slow.** A real run makes graph round trips plus two or
  three model calls. Holding an HTTP connection open for all of it is fragile -
  proxies time out, and the browser shows one spinner with no progress.
* **Progress is observable.** The job exposes the steps completed so far, so the
  dashboard can show the workflow progressing instead of guessing.

State lives in-process and is mirrored into the graph on completion. A job lost
to a restart therefore reads as absent rather than as a phantom "running"
forever, which is the honest failure.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.agent.graph import run_investigation, summarise_state

logger = logging.getLogger(__name__)

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"

TERMINAL = frozenset({COMPLETED, FAILED})


def _as_dict(step: Any) -> dict[str, Any]:
    """Steps are models inside the process and plain dicts on the wire."""
    if isinstance(step, dict):
        return step
    return step.model_dump()


@dataclass
class Job:
    """One in-flight or finished investigation."""

    investigation_id: str
    question: str
    status: str = PENDING
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None

    def to_status(self) -> dict[str, Any]:
        """Shape returned while a job is still in flight."""
        return {
            "investigation_id": self.investigation_id,
            "question": self.question,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": self.steps,
            "error": self.error,
        }


class JobRegistry:
    """Thread-safe store of jobs for this process."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, investigation_id: str, question: str) -> Job:
        job = Job(investigation_id=investigation_id, question=question)
        with self._lock:
            self._jobs[investigation_id] = job
        return job

    def get(self, investigation_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(investigation_id)

    def update(self, investigation_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(investigation_id)
            if job is not None:
                for key, value in fields.items():
                    setattr(job, key, value)

    def append_step(self, investigation_id: str, step: dict[str, Any]) -> None:
        """Record one completed step.

        Exists so a running investigation can publish progress without the
        caller holding the lock itself - `get` takes the same non-reentrant
        lock, so doing this inline is a deadlock.
        """
        with self._lock:
            job = self._jobs.get(investigation_id)
            if job is not None:
                job.steps.append(step)

    def clear(self) -> int:
        with self._lock:
            count = len(self._jobs)
            self._jobs.clear()
            return count


#: Process-wide registry. Module-level because FastAPI workers each keep their
#: own, which is why a restart loses in-flight jobs by design.
registry = JobRegistry()


def run_job(job: Job, repository: Any) -> None:
    """Execute a job synchronously. Called from the background thread pool."""
    registry.update(
        job.investigation_id,
        status=RUNNING,
        started_at=datetime.now(UTC).isoformat(),
    )
    logger.info("Investigation %s started", job.investigation_id)

    def publish(step: Any) -> None:
        """Accumulate steps live so a polling client sees progress."""
        registry.append_step(job.investigation_id, _as_dict(step))

    try:
        state = run_investigation(job.question, repository=repository, on_step=publish)
        summary = summarise_state(state)
        registry.update(
            job.investigation_id,
            status=COMPLETED if state.get("status") == "completed" else FAILED,
            steps=[_as_dict(step) for step in summary.get("steps", [])],
            result=summary,
            error=state.get("error"),
            finished_at=datetime.now(UTC).isoformat(),
        )
        logger.info("Investigation %s finished", job.investigation_id)
    except Exception as exc:  # noqa: BLE001 - a job must never kill the worker
        logger.exception("Investigation %s crashed", job.investigation_id)
        registry.update(
            job.investigation_id,
            status=FAILED,
            error=str(exc),
            finished_at=datetime.now(UTC).isoformat(),
        )