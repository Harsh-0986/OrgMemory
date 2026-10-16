"""Turn a document into graph entities with the model.

This is the AI half of ingestion. The document has already been converted to
Markdown; here the model reads it and proposes entities and relationships, which
are then *validated* before anything reaches the graph.

The validation is the important half. A model asked to produce graph data will
happily invent a label that does not exist, point a relationship at an entity
nobody has heard of, or invent a plausible-looking id for something real. All
three are refused here, with a reason, rather than written and discovered later:

* a label outside `EntityType` would create a node the whole read path cannot
  query, so it is rejected;
* a relationship type outside `RelationType` is rejected for the same reason;
* a relationship whose endpoints cannot be resolved to either an entity in this
  document or an entity already in the graph is rejected - that is the mechanism
  that keeps the "never invent relationships" rule true even with a model in the
  loop.

Everything rejected is reported back. Nothing is dropped silently, because a
misread document and a broken extractor look identical otherwise.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.models.graph import EntityType, RelationType
from app.models.ingest import RejectedItem

logger = logging.getLogger(__name__)

#: Labels the extractor may create. `Investigation` is deliberately absent: it
#: is the agent's own record of a question, not something a document describes.
EXTRACTABLE_LABELS: frozenset[str] = frozenset(
    {
        EntityType.PERSON.value,
        EntityType.SERVICE.value,
        EntityType.PROJECT.value,
        EntityType.INCIDENT.value,
        EntityType.DECISION.value,
        EntityType.DOCUMENT.value,
    }
)

RELATION_TYPES: frozenset[str] = frozenset(r.value for r in RelationType)

MAX_ENTITIES = 40
MAX_RELATIONSHIPS = 60

_ID_SAFE = re.compile(r"[^a-z0-9-]+")
_ID_COLLAPSE = re.compile(r"-{2,}")

EXTRACTOR_SYSTEM = """You convert engineering documents into knowledge-graph facts.

You are given a document and a list of entities already in the graph. Return
JSON only, with this exact shape:

{
  "summary": "one sentence describing what this document is",
  "entities": [
    {"id": "svc-payments-api", "type": "Service", "name": "Payments API",
     "properties": {"criticality": "critical", "description": "..."}}
  ],
  "relationships": [
    {"from_id": "svc-payments-api", "type": "DEPENDS_ON", "to_id": "svc-ledger"}
  ]
}

Rules, all of which are enforced afterwards:

1. "type" must be exactly one of: Person, Service, Project, Incident, Decision,
   Document. Nothing else exists.
2. "type" on a relationship must be exactly one of: OWNS, WORKED_ON, USES,
   DEPENDS_ON, AFFECTED, CAUSED_BY, RESOLVED, AFFECTS, SUPERSEDES, DESCRIBES,
   SUPPORTS, CITED.
3. Do not invent entities that the document does not mention. If the document
   only discusses one service, return one entity.
4. If the document mentions something in the existing-entities list, reuse that
   exact id. Do not create a second id for something that already exists.
5. Ids are lowercase slugs, prefixed by kind: per-, svc-, proj-, inc-, dec-,
   doc-. Follow the existing ids' style.
6. Every relationship endpoint must be either an entity you are returning or an
   id from the existing-entities list. Never reference anything else.
7. No self-relationships.
8. Prefer fewer, better-supported facts. An empty list is a valid answer.
9. Return JSON and nothing else - no prose, no code fences."""

EXTRACTOR_USER = """Document title: {title}

--- DOCUMENT START ---
{content}
--- DOCUMENT END ---

Entities already in the graph (reuse these ids exactly when the document refers
to them):
{known}

Return the JSON object described in your instructions."""


class ExtractedEntity(BaseModel):
    """A validated entity the model proposed."""

    id: str
    type: EntityType
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractedRelationship(BaseModel):
    """A validated relationship the model proposed."""

    from_id: str
    type: RelationType
    to_id: str


class ExtractionOutcome(BaseModel):
    """What the extractor produced, including what it refused."""

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)
    rejected: list[RejectedItem] = Field(default_factory=list)
    summary: str = ""
    #: False when the model was unavailable and nothing was extracted, so a
    #: caller can tell "the document had no entities" from "there was no model".
    model_used: bool = False


def slugify(raw: str) -> str:
    """Normalise a proposed id to the lowercase, prefix-style slug we use."""
    slug = _ID_SAFE.sub("-", raw.strip().lower()).strip("-")
    return _ID_COLLAPSE.sub("-", slug)


def _known_catalogue(known: dict[str, str], limit: int = 150) -> str:
    """Render existing entities for the prompt, smallest useful form."""
    if not known:
        return "(the graph is empty)"
    items = [f"  {eid} - {name}" for eid, name in list(known.items())[:limit]]
    if len(known) > limit:
        items.append(f"  ... and {len(known) - limit} more")
    return "\n".join(items)


def build_prompt(title: str, content: str, known: dict[str, str]) -> tuple[str, str]:
    """The (system, user) pair handed to the model. Separated out to be testable."""
    return (
        EXTRACTOR_SYSTEM,
        EXTRACTOR_USER.format(
            title=title or "(untitled)",
            content=content,
            known=_known_catalogue(known),
        ),
    )


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def validate_extraction(
    payload: dict[str, Any],
    known_ids: set[str],
) -> ExtractionOutcome:
    """Validate a raw extractor response into something safe to write.

    Pure and deterministic: no model, no database. That is deliberate, because
    this is the security boundary for ingestion and it should be cheap to test
    exhaustively.
    """
    outcome = ExtractionOutcome(model_used=True)
    summary = payload.get("summary")
    if isinstance(summary, str):
        outcome.summary = summary.strip()[:400]

    # -- entities ---------------------------------------------------------
    seen_ids: set[str] = set()
    for raw in _as_list(payload.get("entities")):
        if len(outcome.entities) >= MAX_ENTITIES:
            outcome.rejected.append(
                RejectedItem(
                    item=str(raw)[:120],
                    reason=f"more than {MAX_ENTITIES} entities in one document",
                )
            )
            continue
        if not isinstance(raw, dict):
            outcome.rejected.append(
                RejectedItem(item=str(raw)[:120], reason="entity was not an object")
            )
            continue

        label = raw.get("type")
        if label not in EXTRACTABLE_LABELS:
            outcome.rejected.append(
                RejectedItem(
                    item=f"{raw.get('id', '?')} (type={label!r})",
                    reason=f"unknown label; allowed: {sorted(EXTRACTABLE_LABELS)}",
                )
            )
            continue

        entity_id = slugify(str(raw.get("id") or raw.get("name") or ""))
        if not entity_id:
            outcome.rejected.append(
                RejectedItem(item=str(raw.get("name", "?")), reason="entity had no usable id")
            )
            continue

        if entity_id in seen_ids:
            # Same id twice in one response is a duplicate, not an error worth
            # reporting loudly - the first wins.
            continue
        seen_ids.add(entity_id)

        properties = raw.get("properties")
        outcome.entities.append(
            ExtractedEntity(
                id=entity_id,
                type=EntityType(label),
                name=str(raw.get("name") or entity_id),
                properties=properties if isinstance(properties, dict) else {},
            )
        )

    # Every id a relationship may legally point at.
    resolvable = {e.id for e in outcome.entities} | known_ids

    # -- relationships ----------------------------------------------------
    seen_rels: set[tuple[str, str, str]] = set()
    for raw in _as_list(payload.get("relationships")):
        if len(outcome.relationships) >= MAX_RELATIONSHIPS:
            outcome.rejected.append(
                RejectedItem(
                    item=str(raw)[:120],
                    reason=f"more than {MAX_RELATIONSHIPS} relationships in one document",
                )
            )
            continue
        if not isinstance(raw, dict):
            outcome.rejected.append(
                RejectedItem(item=str(raw)[:120], reason="relationship was not an object")
            )
            continue

        rel_type = raw.get("type")
        from_id = slugify(str(raw.get("from_id") or ""))
        to_id = slugify(str(raw.get("to_id") or ""))

        if rel_type not in RELATION_TYPES:
            outcome.rejected.append(
                RejectedItem(
                    item=f"{from_id} -{rel_type}-> {to_id}",
                    reason=f"unknown relationship type; allowed: {sorted(RELATION_TYPES)}",
                )
            )
            continue

        if not from_id or not to_id:
            outcome.rejected.append(
                RejectedItem(
                    item=f"{from_id} -{rel_type}-> {to_id}",
                    reason="relationship is missing an endpoint",
                )
            )
            continue

        if from_id == to_id:
            outcome.rejected.append(
                RejectedItem(
                    item=f"{from_id} -{rel_type}-> {to_id}",
                    reason="relationship points at itself",
                )
            )
            continue

        unresolved = [i for i in (from_id, to_id) if i not in resolvable]
        if unresolved:
            outcome.rejected.append(
                RejectedItem(
                    item=f"{from_id} -{rel_type}-> {to_id}",
                    reason=(
                        f"endpoint(s) {unresolved} are neither in this document nor "
                        "in the graph"
                    ),
                )
            )
            continue

        key = (from_id, str(rel_type), to_id)
        if key in seen_rels:
            continue
        seen_rels.add(key)

        outcome.relationships.append(
            ExtractedRelationship(
                from_id=from_id,
                type=RelationType(rel_type),
                to_id=to_id,
            )
        )

    return outcome


def extract_graph(
    title: str,
    markdown: str,
    known: dict[str, str] | None = None,
    *,
    invoke: Any | None = None,
) -> ExtractionOutcome:
    """Ask the model for entities and relationships, then validate them.

    `invoke` is the seam for tests: a callable shaped like the agent's `_invoke`
    returning the model's raw text. Passing one means no model is called at all,
    which is how the ingestion tests run without spending quota.
    """
    from app.agent.nodes import _extract_json, _invoke

    known = known or {}
    system, user = build_prompt(title, markdown, known)
    call = invoke if invoke is not None else _invoke

    from app.config import get_settings

    raw = call(system, user, timeout=get_settings().agent_query_timeout_seconds)
    if not raw:
        # No model: an honest empty result, flagged as such.
        logger.info("Extractor had no model available; nothing extracted")
        return ExtractionOutcome(model_used=False)

    payload = _extract_json(raw)
    if payload is None:
        logger.warning("Extractor returned unparseable output")
        return ExtractionOutcome(
            model_used=True,
            rejected=[
                RejectedItem(
                    item=raw.strip()[:200],
                    reason="model output was not valid JSON",
                )
            ],
        )

    return validate_extraction(payload, set(known))
