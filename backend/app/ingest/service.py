"""Ingest an uploaded document into the knowledge graph.

The order below is the whole point, so it is worth stating plainly:

1. **Convert** the upload to Markdown locally. Free, no network.
2. **Extract** entities and relationships with the model, then validate every
   proposal against the graph's allowlists. Anything invalid is refused with a
   reason and never reaches the graph.
3. **Write** the document, then any entity that does not already exist, then the
   validated relationships, then provenance edges from the document to
   everything it mentions.

Two rules shape the writing:

* **Existing entities are never overwritten.** If the model proposes an id that
  is already in the graph, the document is linked to that entity instead of
  restating it. A model that misreads a sentence must not be able to silently
  rewrite curated data - the worst it can do is add a link, which is visible and
  reversible.
* **The document always gets provenance.** The `DESCRIBES` edges are derived
  from the document's own entity list, not from what the model proposed for
  relationships, so a document stays reachable from the things it talks about
  even if the extractor returned nothing.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

from app.graph.repository import GraphRepository
from app.ingest.documents import to_markdown
from app.ingest.extract import ExtractionOutcome, extract_graph
from app.models.graph import utcnow
from app.models.ingest import IngestedEntity, IngestReport, IngestStep

logger = logging.getLogger(__name__)

#: Called as each phase completes, so a slow ingestion can report progress
#: instead of showing one spinner for the whole of it.
Progress = Callable[[IngestStep], None]

#: Matches the vocabulary the seeded documents use, so an uploaded ADR is the
#: same kind of thing as the ADRs already in the graph.
SOURCE_TYPES: frozenset[str] = frozenset(
    {"upload", "adr", "runbook", "postmortem", "handbook", "spec", "analysis", "note"}
)


def document_id_for(title: str, markdown: str) -> str:
    """A stable id derived from the content.

    Re-uploading the same document therefore updates one node rather than
    accumulating near-duplicates, and the id is reproducible across processes -
    unlike a uuid, which would create a new document on every retry.
    """
    digest = hashlib.sha256(f"{title}\n{markdown}".encode()).hexdigest()[:12]
    return f"doc-ingested-{digest}"


def ingest_document(
    *,
    repository: GraphRepository,
    filename: str = "",
    data: bytes | None = None,
    text: str | None = None,
    title: str | None = None,
    source_type: str = "upload",
    source_uri: str = "",
    invoke: Any | None = None,
    on_progress: Progress | None = None,
) -> IngestReport:
    """Convert, extract and write one document.

    `text` bypasses conversion entirely, which is what the paste box uses.
    `invoke` is the test seam: supplying it means no model is called.
    `on_progress` is called as each phase finishes, which is how a queued
    ingestion reports progress while the model is thinking.
    """
    if source_type not in SOURCE_TYPES:
        source_type = "upload"

    def publish(phase: str, title: str, detail: str, started: float) -> None:
        if on_progress is not None:
            on_progress(
                IngestStep(
                    phase=phase,
                    title=title,
                    detail=detail,
                    duration_ms=round((time.perf_counter() - started) * 1000, 1),
                )
            )

    # -- 1. to Markdown ---------------------------------------------------
    phase_started = time.perf_counter()
    if text is not None and text.strip():
        markdown = text.strip()
        truncated = False
    else:
        if data is None:
            raise ValueError("Either `text` or `data` must be provided.")
        converted = to_markdown(filename or "upload.txt", data)
        markdown = converted.markdown
        truncated = converted.truncated
    publish(
        "convert",
        "Converted to Markdown" if data is not None else "Took the pasted text",
        f"{len(markdown):,} characters"
        + (" (trimmed before reading)" if truncated else ""),
        phase_started,
    )

    resolved_title = preview_title(
        title=title or "", filename=filename, text=markdown
    )

    # -- 2. extract -------------------------------------------------------
    # The catalogue is fetched before extraction so the model can reuse the ids
    # that already exist instead of proposing a second id for the same service.
    phase_started = time.perf_counter()
    known = repository.entity_catalogue()
    outcome = extract_graph(resolved_title, markdown, known, invoke=invoke)
    if outcome.model_used:
        extract_title = "Read the document for entities"
        extract_detail = (
            f"{len(outcome.entities)} entities, {len(outcome.relationships)} relationships"
            + (f", {len(outcome.rejected)} refused" if outcome.rejected else "")
        )
    elif outcome.model_error:
        # The call was made and failed. Saying "no model available" here would be
        # a lie that sends the reader to their configuration for the wrong
        # problem, which is what a slow model used to look like.
        extract_title = "The model call failed"
        extract_detail = f"{outcome.model_error} — the document is still stored and citable"
    else:
        extract_title = "No model available"
        extract_detail = "nothing extracted; the document is still stored and citable"
    publish("extract", extract_title, extract_detail, phase_started)

    # -- 3. write ---------------------------------------------------------
    phase_started = time.perf_counter()
    document_id = document_id_for(resolved_title, markdown)
    repository.upsert_document(
        {
            "id": document_id,
            "title": resolved_title,
            "source_type": source_type,
            "source_uri": source_uri,
            "content": markdown,
            "ingested_at": utcnow().isoformat(),
            "extracted_by_model": bool(outcome.model_used),
            "truncated_for_extraction": bool(truncated),
        }
    )

    # Only genuinely new entities are written. An id that already exists is a
    # reference to something we already know, and restating it would let a
    # misreading overwrite curated facts.
    new_entities = [e for e in outcome.entities if e.id not in known]
    already_known = [e for e in outcome.entities if e.id in known]

    written_entities = 0
    if new_entities:
        written_entities = repository.upsert_entities(
            [
                {"id": e.id, "type": e.type.value, "properties": _props_for(e)}
                for e in new_entities
            ]
        )

    written_relationships = 0
    if outcome.relationships:
        written_relationships = repository.upsert_relationships(
            [
                {"from_id": r.from_id, "type": r.type.value, "to_id": r.to_id}
                for r in outcome.relationships
            ]
        )

    # Provenance: everything the document contributed or referred to.
    touched = [e.id for e in outcome.entities]
    linked = repository.link_document_to_entities(document_id, touched)
    publish(
        "write",
        "Wrote it into the graph",
        f"{written_entities} new entities, {written_relationships} relationships, "
        f"{linked} citations",
        phase_started,
    )

    logger.info(
        "Ingested %s: %d new entities, %d relationships, %d citations%s",
        document_id,
        written_entities,
        written_relationships,
        linked,
        "" if outcome.model_used else " (no model available)",
    )

    return IngestReport(
        document_id=document_id,
        title=resolved_title,
        source_type=source_type,
        model_used=outcome.model_used,
        summary=outcome.summary,
        model_error=outcome.model_error,
        entities_created=[
            IngestedEntity(id=e.id, type=e.type.value, name=e.name) for e in new_entities
        ],
        entities_linked=[
            IngestedEntity(id=e.id, type=e.type.value, name=e.name)
            for e in already_known
        ],
        relationships_created=[
            f"{r.from_id} -{r.type.value}-> {r.to_id}" for r in outcome.relationships
        ],
        rejected=outcome.rejected,
        citations_linked=linked,
        truncated=truncated,
        markdown_chars=len(markdown),
    )


def _props_for(entity: Any) -> dict[str, Any]:
    """Node properties for a newly created entity.

    FalkorDB stores primitives and arrays of primitives only, so anything else
    the model produced is stringified rather than dropped - losing a field
    silently is worse than storing it as text.
    """
    props: dict[str, Any] = {"name": entity.name}
    for key, value in (entity.properties or {}).items():
        if value is None:
            # FalkorDB has no null property value; an absent property and a
            # null one mean the same thing here, so skip rather than coerce.
            continue
        if isinstance(value, str | int | float | bool):
            props[str(key)] = value
        elif isinstance(value, list) and all(
            isinstance(v, str | int | float | bool) for v in value
        ):
            props[str(key)] = value
        else:
            props[str(key)] = str(value)
    return props


def title_from_text(markdown: str) -> str:
    """A title from the document's own first line, for pasted text.

    Pasted text has no filename, and "Uploaded document" tells the reader
    nothing - least of all which document it is when there are several. The first
    non-empty line is almost always the heading the author already wrote, so the
    obvious title is the one that was sitting right there.
    """
    for line in markdown.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned:
            return cleaned[:120]
    return ""


def title_from(filename: str) -> str:
    """A serviceable title from a filename when the user did not give one."""
    stem = filename.rsplit("/", 1)[-1]
    for suffix in (".markdown", ".md", ".txt", ".html", ".pdf", ".docx", ".pptx", ".xlsx"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    return stem.replace("_", " ").replace("-", " ").strip()


def preview_title(*, title: str = "", filename: str = "", text: str = "") -> str:
    """The title an ingestion will end up with, without ingesting it.

    A queued upload returns before any of this is known, but the progress header
    should still name the document. This is the same resolution
    `ingest_document` performs, so the preview cannot drift from the result.
    """
    return (
        (title or "").strip()
        or title_from(filename)
        or title_from_text(text)
        or "Uploaded document"
    )


__all__ = [
    "SOURCE_TYPES",
    "ExtractionOutcome",
    "document_id_for",
    "ingest_document",
    "preview_title",
    "title_from",
    "title_from_text",
]
