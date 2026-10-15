"""Graph schema: constraints and indexes.

Run before seeding.  FalkorDB supports the standard OpenCypher
`CREATE CONSTRAINT ... FOR ... REQUIRE ... IS UNIQUE` syntax, which keeps the
graph free of duplicate nodes and makes id lookups index-backed.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.graph.client import get_graph
from app.models.graph import EntityType

logger = logging.getLogger(__name__)

# One unique constraint per node label. Every entity carries a stable string id
# (e.g. `svc-checkout`) that the rest of the system uses as its primary key.
CONSTRAINTS: list[str] = [
    f"CREATE CONSTRAINT {label}_id IF NOT EXISTS "
    f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
    for label in (
        EntityType.PERSON.value,
        EntityType.SERVICE.value,
        EntityType.PROJECT.value,
        EntityType.INCIDENT.value,
        EntityType.DECISION.value,
        EntityType.DOCUMENT.value,
        EntityType.INVESTIGATION.value,
    )
]

# Full-text indexes power document and decision lookup by free text.
FULLTEXT_INDEXES: list[str] = [
    "CALL db.idx.fulltext.createNodeIndex('Document', 'title', 'content')",
    "CALL db.idx.fulltext.createNodeIndex('Decision', 'title', 'rationale')",
    "CALL db.idx.fulltext.createNodeIndex('Incident', 'title', 'summary')",
    "CALL db.idx.fulltext.createNodeIndex('Service', 'name', 'description')",
]


def apply_schema() -> dict[str, int]:
    """Apply constraints and indexes. Safe to run repeatedly."""
    graph = get_graph()
    applied = 0

    for statement in CONSTRAINTS:
        try:
            graph.query(statement)
            applied += 1
        except Exception as exc:
            # An existing identical constraint is reported as an error by
            # FalkorDB; that is expected on repeat runs and not a failure.
            logger.debug("Constraint skipped: %s (%s)", statement, exc)

    for statement in FULLTEXT_INDEXES:
        try:
            graph.query(statement)
            applied += 1
        except Exception as exc:
            logger.debug("Full-text index skipped: %s (%s)", statement, exc)

    logger.info("Applied %d schema statements", applied)
    return {"statements_applied": applied, "constraints": len(CONSTRAINTS)}


def reset_graph() -> None:
    """Delete the entire graph. Used to make seeding repeatable from scratch."""
    settings = get_settings()
    graph = get_graph()
    try:
        graph.delete()
        logger.warning("Deleted graph '%s'", settings.falkordb_graph)
    except Exception as exc:
        logger.debug("Nothing to delete for graph '%s': %s", settings.falkordb_graph, exc)