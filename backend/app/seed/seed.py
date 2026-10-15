"""Repeatable graph seeding.

Every write is parameterised through FalkorDB's `params` dict, and every node is
upserted with `MERGE`, so running the seeder twice leaves the graph in the same
state instead of duplicating it. Relationships are grouped by type because
Cypher cannot parameterise a relationship type.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from typing import Any

from app.config import get_settings
from app.graph import client as graph_client
from app.graph.schema import apply_schema, reset_graph
from app.seed import data

logger = logging.getLogger(__name__)


class SeedValidationError(RuntimeError):
    """Raised when the dataset is internally inconsistent."""


def validate_dataset() -> None:
    """Fail fast if the dataset references entities that do not exist.

    This is the first line of defence behind the spec's rule that the agent must
    never invent relationships - the ground truth itself has to be sound.
    """
    collections = {
        "people": data.PEOPLE,
        "services": data.SERVICES,
        "projects": data.PROJECTS,
        "incidents": data.INCIDENTS,
        "decisions": data.DECISIONS,
        "documents": data.DOCUMENTS,
    }

    # Incidents, decisions and documents are titled; people, services and
    # projects are named. Requiring the right field per label keeps this a real
    # check rather than a rubber stamp.
    label_required = {
        "people": {"id", "name", "role", "team"},
        "services": {"id", "name", "description", "criticality"},
        "projects": {"id", "name", "status"},
        "incidents": {"id", "title", "severity", "occurred_at", "summary"},
        "decisions": {"id", "title", "date", "rationale", "status"},
        "documents": {"id", "title", "source_type", "source_uri", "content"},
    }

    seen: set[str] = set()
    duplicates: list[str] = []
    for label, rows in collections.items():
        required = label_required[label]
        for row in rows:
            entity_id = row["id"]
            if entity_id in seen:
                duplicates.append(entity_id)
            seen.add(entity_id)
            missing = required - set(row)
            if missing:
                raise SeedValidationError(
                    f"{label} entity '{entity_id}' is missing required fields: {sorted(missing)}"
                )
    if duplicates:
        raise SeedValidationError(f"Duplicate entity ids: {sorted(set(duplicates))}")

    dangling = [
        (src, rel, dst)
        for src, rel, dst in data.all_relationships()
        if src not in seen or dst not in seen
    ]
    if dangling:
        raise SeedValidationError(
            f"Relationships reference unknown entities: {dangling[:5]}"
        )

    logger.info("Dataset validated: %s", data.seed_summary())


def _load_nodes(graph: Any, label: str, rows: list[dict[str, Any]]) -> int:
    """Upsert one node label via a single parameterised query."""
    if not rows:
        return 0
    graph.query(
        f"UNWIND $rows AS row "  # noqa: S608 - label is a fixed literal from COLLECTIONS
        f"MERGE (n:{label} {{id: row.id}}) "
        "SET n += row",
        params={"rows": rows},
    )
    return len(rows)


def _load_relationships(
    graph: Any, rel_type: str, triples: list[tuple[str, str, str]]
) -> int:
    """Upsert one relationship type via a single parameterised query."""
    if not triples:
        return 0
    rows = [{"from_id": src, "to_id": dst} for src, _, dst in triples]
    graph.query(
        f"UNWIND $rows AS row "  # noqa: S608 - rel_type comes from a fixed mapping
        "MATCH (a) WHERE a.id = row.from_id "
        "MATCH (b) WHERE b.id = row.to_id "
        f"MERGE (a)-[r:{rel_type}]->(b)",
        params={"rows": rows},
    )
    return len(triples)


def seed(reset: bool = False) -> dict[str, Any]:
    """Populate the graph. Returns a summary of what was written."""
    settings = get_settings()
    if not graph_client.ping():
        raise SeedValidationError(
            "Cannot reach FalkorDB. Check FALKORDB_HOST / FALKORDB_PASSWORD in your .env."
        )

    validate_dataset()

    if reset:
        logger.warning("Resetting graph '%s'", settings.falkordb_graph)
        reset_graph()
        # The graph handle is invalidated by delete(); force a fresh selection.
        graph_client.reset_connection()

    apply_schema()
    graph = graph_client.get_graph()

    counts: dict[str, int] = {}
    counts["Person"] = _load_nodes(graph, "Person", data.PEOPLE)
    counts["Service"] = _load_nodes(graph, "Service", data.SERVICES)
    counts["Project"] = _load_nodes(graph, "Project", data.PROJECTS)
    counts["Incident"] = _load_nodes(graph, "Incident", data.INCIDENTS)
    counts["Decision"] = _load_nodes(graph, "Decision", data.DECISIONS)
    counts["Document"] = _load_nodes(graph, "Document", data.DOCUMENTS)

    grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    for src, rel_type, dst in data.all_relationships():
        grouped[rel_type].append((src, rel_type, dst))

    rel_counts: dict[str, int] = {}
    for rel_type, triples in grouped.items():
        rel_counts[rel_type] = _load_relationships(graph, rel_type, triples)

    summary = {
        "graph": settings.falkordb_graph,
        "nodes": counts,
        "relationships": rel_counts,
        "total_nodes": sum(counts.values()),
        "total_relationships": sum(rel_counts.values()),
    }
    logger.info(
        "Seed complete: %d nodes, %d relationships",
        summary["total_nodes"],
        summary["total_relationships"],
    )
    return summary


def main() -> None:  # pragma: no cover - CLI entrypoint
    parser = argparse.ArgumentParser(description="Seed the OrgMemory graph.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the graph before seeding (fresh start).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    summary = seed(reset=args.reset)
    print("\nSeed summary")
    print("------------")
    for key, value in summary["nodes"].items():
        print(f"  {key:<14} {value}")
    print(f"  {'relationships':<14} {summary['total_relationships']}")
    print(f"\n  graph: {summary['graph']}")


if __name__ == "__main__":  # pragma: no cover
    main()