"""Typed access to the knowledge graph.

Every public method here is a "graph tool": deterministic, bounded, and
independent of the LLM. The agent composes these; it never writes its own
queries. Each method returns domain models (not raw rows) so that provenance -
node ids, relationship types, hop counts - is preserved end to end.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.config import get_settings
from app.graph import queries
from app.graph.client import get_graph
from app.models.graph import (
    Edge,
    EntityType,
    GraphPath,
    ImpactedService,
    NodeRef,
    RelationType,
    utcnow,
)

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _rows(template: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute an allowlisted template and return normalised rows.

    A single choke point for timeouts and error translation: a graph failure
    becomes a `GraphUnavailable` the API can render as a 503, never a 500 with
    a stack trace.
    """
    from app.graph.client import GraphUnavailable

    timeout = int(get_settings().agent_query_timeout_seconds)
    try:
        result = get_graph().query(template, params, timeout)
    except Exception as exc:
        logger.error("Graph query failed: %s | params=%s", exc, params)
        raise GraphUnavailable(f"Graph query failed: {exc}") from exc
    return [queries.row_to_dict(row) for row in (result.result_set or [])]


def _as_node_ref(node_id: str, label: str | None, name: str, **props: Any) -> NodeRef:
    """Build a `NodeRef`, tolerating unknown or malformed labels."""
    try:
        entity_type = EntityType(label) if label else EntityType.SERVICE
    except ValueError:
        entity_type = EntityType.SERVICE
    return NodeRef(id=node_id, type=entity_type, name=name or node_id, properties=props)


def _person_ref(row: dict[str, Any], prefix: str = "person") -> NodeRef:
    """Build a `NodeRef` for a person from an aliased result row."""
    return _as_node_ref(
        row.get(f"{prefix}_id", ""),
        EntityType.PERSON.value,
        row.get(f"{prefix}_name", ""),
        role=row.get(f"{prefix}_role", ""),
        team=row.get(f"{prefix}_team", ""),
    )


def _service_ref(row: dict[str, Any]) -> NodeRef:
    """Build a `NodeRef` for a service from a result row."""
    return _as_node_ref(
        row.get("id", ""),
        EntityType.SERVICE.value,
        row.get("name", ""),
        description=row.get("description", ""),
        criticality=row.get("criticality", "medium"),
        tier=row.get("tier", ""),
    )


def _rows_to_paths(rows: list[dict[str, Any]]) -> list[GraphPath]:
    """Rehydrate flat `nodes` / `rel_types` rows into `GraphPath` objects."""
    paths: list[GraphPath] = []
    for row in rows:
        raw_nodes = row.get("nodes") or []
        raw_rels = row.get("rel_types") or []
        if not raw_nodes:
            continue

        nodes = [
            _as_node_ref(n.get("id", ""), n.get("label"), n.get("name") or n.get("id", ""))
            for n in raw_nodes
        ]
        edges: list[Edge] = []
        for idx, rel_type in enumerate(raw_rels):
            if idx + 1 >= len(nodes):
                break
            src, dst = nodes[idx], nodes[idx + 1]
            try:
                relation = RelationType(rel_type)
            except ValueError:
                relation = RelationType.DESCRIBES
            edges.append(
                Edge(
                    type=relation,
                    from_id=src.id,
                    from_type=src.type,
                    to_id=dst.id,
                    to_type=dst.type,
                )
            )
        if edges:
            paths.append(
                GraphPath(
                    nodes=nodes,
                    edges=edges,
                    explanation=f"{row.get('depth', len(edges))}-hop path",
                )
            )
    return paths


def _dedupe_paths(paths: list[GraphPath]) -> list[GraphPath]:
    """Drop duplicate paths, keeping the first (shortest, since we sort)."""
    seen: set[str] = set()
    unique: list[GraphPath] = []
    for path in paths:
        key = path.signature()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


class GraphRepository:
    """Deterministic graph operations exposed to the agent and the API."""

    # -- Overview / exploration ------------------------------------------
    def overview(self) -> dict[str, Any]:
        """Node and relationship counts, plus criticality and severity mix."""
        node_rows = _rows(queries.GRAPH_OVERVIEW, {"limit": queries.default_limit(50)})
        edge_rows = _rows(queries.GRAPH_EDGE_COUNTS, {"limit": queries.default_limit(50)})

        labels = {r["label"]: int(r["count"]) for r in node_rows}
        relationships = {r["rel_type"]: int(r["count"]) for r in edge_rows}

        services = _rows(
            queries.SERVICE_SEARCH, {"needle": "", "limit": queries.default_limit(200)}
        )
        criticality: dict[str, int] = {}
        for svc in services:
            level = svc.get("criticality") or "unknown"
            criticality[level] = criticality.get(level, 0) + 1

        return {
            "graph": get_settings().falkordb_graph,
            "node_counts": labels,
            "relationship_counts": relationships,
            "total_nodes": sum(labels.values()),
            "total_relationships": sum(relationships.values()),
            "criticality_breakdown": criticality,
        }

    def neighborhood(self, entity_id: str, depth: int | None = None) -> dict[str, Any]:
        """The subgraph around one entity, as nodes, edges and paths."""
        limit = queries.default_limit(queries.default_limit())
        rows = _rows(
            queries.GRAPH_NEIGHBORHOOD,
            {
                "entity_id": entity_id,
                "max_depth": queries.max_depth(depth),
                "limit": limit,
            },
        )
        paths = _dedupe_paths(_rows_to_paths(rows))

        node_map: dict[str, NodeRef] = {}
        edges: dict[tuple[str, str, str], Edge] = {}
        for path in paths:
            for node in path.nodes:
                node_map.setdefault(node.id, node)
            for edge in path.edges:
                edges[(edge.type.value, edge.from_id, edge.to_id)] = edge

        return {
            "entity_id": entity_id,
            "depth": queries.max_depth(depth),
            "nodes": list(node_map.values()),
            "edges": list(edges.values()),
            "paths": paths,
        }

    # -- Entity resolution -------------------------------------------------
    def find_services(self, needle: str) -> list[NodeRef]:
        """Fuzzy-match a service by name, id or description."""
        if not needle or not needle.strip():
            return []
        rows = _rows(
            queries.SERVICE_SEARCH,
            {"needle": needle.strip(), "limit": queries.default_limit(10)},
        )
        return [_service_ref(r) for r in rows]

    def all_services(self) -> list[dict[str, Any]]:
        """Every service as a plain dict, used by the planner's local matcher.

        The planner needs the full catalogue in-process to resolve names like
        "Payment Service A" without spending an extra tool call.
        """
        return _rows(
            queries.SERVICE_SEARCH,
            {"needle": "", "limit": queries.default_limit(500)},
        )

    def find_entities(self, needle: str) -> list[NodeRef]:
        """Fuzzy-match any entity type by name, title or id."""
        if not needle or not needle.strip():
            return []
        rows = _rows(
            queries.ENTITY_SEARCH,
            {"needle": needle.strip(), "limit": queries.default_limit(10)},
        )
        return [
            _as_node_ref(r["id"], r.get("label"), r.get("name", "")) for r in rows
        ]

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        """Fetch one entity's raw properties by exact id."""
        rows = _rows(queries.ENTITY_BY_ID, {"entity_id": entity_id, "limit": 1})
        if not rows:
            return None
        row = rows[0]
        return {"id": row.get("id"), "label": row.get("label"), "properties": row.get("props", {})}

    # -- Dependency analysis ----------------------------------------------
    def impacted_services(self, service_id: str, depth: int | None = None) -> list[ImpactedService]:
        """Services that would break if `service_id` changed or failed.

        Traverses DEPENDS_ON inbound, so the result is everything downstream of
        the change, at the minimum hop count.
        """
        rows = _rows(
            queries.DEPENDENCY_IMPACT,
            {
                "service_id": service_id,
                "max_depth": queries.max_depth(depth),
                "limit": queries.default_limit(),
            },
        )
        if not rows:
            return []

        owners_by_service = self.owners_for([service_id, *[r["id"] for r in rows]])

        impacted: list[ImpactedService] = []
        for row in rows:
            svc_id = row["id"]
            impacted.append(
                ImpactedService(
                    service=_as_node_ref(
                        svc_id,
                        EntityType.SERVICE.value,
                        row.get("name", ""),
                        description=row.get("description", ""),
                        criticality=row.get("criticality", "medium"),
                        tier=row.get("tier", ""),
                    ),
                    depth=int(row.get("depth", 1)),
                    owners=owners_by_service.get(svc_id, []),
                    reasons=[
                        f"Depends on the changed service through {row.get('depth', 1)} "
                        f"dependency hop(s)."
                    ],
                    criticality=row.get("criticality", "medium"),
                )
            )
        return impacted

    def dependency_paths(
        self, service_id: str, depth: int | None = None
    ) -> list[GraphPath]:
        """The concrete paths from impacted services back to the changed one."""
        rows = _rows(
            queries.DEPENDENCY_PATHS,
            {
                "service_id": service_id,
                "max_depth": queries.max_depth(depth),
                "limit": queries.default_limit(),
            },
        )
        return _dedupe_paths(_rows_to_paths(rows))

    def upstream_dependencies(self, service_id: str, depth: int | None = None) -> list[dict[str, Any]]:
        """What a service itself depends on."""
        return _rows(
            queries.UPSTREAM_DEPENDENCIES,
            {
                "service_id": service_id,
                "max_depth": queries.max_depth(depth),
                "limit": queries.default_limit(),
            },
        )

    def shared_dependencies(self, service_a: str, service_b: str) -> list[dict[str, Any]]:
        """Dependencies both services rely on - the core migration risk surface."""
        return _rows(
            queries.SHARED_DEPENDENCIES,
            {"a_id": service_a, "b_id": service_b, "limit": queries.default_limit()},
        )

    # -- People -------------------------------------------------------------
    def owners_for(self, service_ids: list[str]) -> dict[str, list[NodeRef]]:
        """Map each service id to its owning people."""
        if not service_ids:
            return {}
        rows = _rows(
            queries.SERVICE_OWNERS,
            {"service_ids": list(dict.fromkeys(service_ids)), "limit": queries.default_limit()},
        )
        owners: dict[str, list[NodeRef]] = {}
        for row in rows:
            owners.setdefault(row.get("service_id", ""), []).append(_person_ref(row))
        return owners

    def relevant_engineers(self, service_ids: list[str]) -> list[dict[str, Any]]:
        """People with project or incident history on the given services."""
        if not service_ids:
            return []
        rows = _rows(
            queries.RELEVANT_ENGINEERS,
            {"service_ids": list(dict.fromkeys(service_ids)), "limit": queries.default_limit()},
        )
        # Rank by distinct engagements so the busiest reviewer surfaces first.
        engagement: dict[str, set[str]] = {}
        for row in rows:
            engagement.setdefault(row["person_id"], set()).add(row["project_id"])

        ranked = sorted(
            rows,
            key=lambda r: (-len(engagement.get(r["person_id"], ())), r["person_name"]),
        )
        seen: set[tuple[str, str]] = set()
        unique: list[dict[str, Any]] = []
        for row in ranked:
            key = (row["person_id"], row["project_id"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    # -- Incidents / decisions / documents ---------------------------------
    def related_incidents(self, service_ids: list[str]) -> list[dict[str, Any]]:
        """Incidents that affected any of the given services.

        `cause_names` is deliberately empty when the graph has no CAUSED_BY edge;
        the agent must report that as unknown rather than guessing.
        """
        if not service_ids:
            return []
        return _rows(
            queries.RELATED_INCIDENTS,
            {"service_ids": list(dict.fromkeys(service_ids)), "limit": queries.default_limit()},
        )

    def decision_history(self, service_ids: list[str]) -> list[dict[str, Any]]:
        """Architecture decisions affecting the given services, newest first."""
        if not service_ids:
            return []
        return _rows(
            queries.DECISION_HISTORY,
            {"service_ids": list(dict.fromkeys(service_ids)), "limit": queries.default_limit()},
        )

    def supporting_documents(self, entity_ids: list[str]) -> list[dict[str, Any]]:
        """Documents describing or supporting the given entities."""
        if not entity_ids:
            return []
        return _rows(
            queries.SUPPORTING_DOCUMENTS,
            {"entity_ids": list(dict.fromkeys(entity_ids)), "limit": queries.default_limit()},
        )

    # -- Persistent memory --------------------------------------------------
    def save_investigation(
        self,
        *,
        investigation_id: str,
        question: str,
        answer: str,
        summary: str,
        status: str = "completed",
        cited_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist an investigation and its citations as first-class graph edges.

        Storing citations as `CITED` relationships - rather than a blob of text -
        is what lets a later session traverse from a past investigation back into
        the services, people and decisions it touched.
        """
        cited = list(dict.fromkeys(cited_ids or []))
        props = {
            "id": investigation_id,
            "question": question,
            "answer": answer,
            "summary": summary,
            "status": status,
            "cited_ids": cited,
            "created_at": utcnow().isoformat(),
            "metadata": metadata or {},
        }
        _rows(queries.STORE_INVESTIGATION, {"props": props})

        # Link citations to nodes that actually exist, so a bad reference
        # cannot pollute the graph.
        linkable: list[dict[str, Any]] = []
        for cid in cited:
            if self.get_entity(cid):
                linkable.append({"id": cid})
        if linkable:
            _rows(
                queries.LINK_CITATIONS,
                {"investigation_id": investigation_id, "citations": linkable},
            )
        return investigation_id

    def list_investigations(self, limit: int = 20) -> list[dict[str, Any]]:
        """Recent investigations, newest first."""
        rows = _rows(queries.PREVIOUS_INVESTIGATIONS, {"limit": queries.default_limit(limit)})
        return [
            {
                "id": r.get("id"),
                "question": r.get("question"),
                "created_at": r.get("created_at"),
                "summary": r.get("summary"),
                "cited_ids": r.get("cited_ids") or [],
            }
            for r in rows
        ]

    def get_investigation(self, investigation_id: str) -> dict[str, Any] | None:
        """One stored investigation plus the entities it cited."""
        rows = _rows(
            queries.INVESTIGATION_BY_ID,
            {"investigation_id": investigation_id, "limit": 1},
        )
        if not rows:
            return None
        props = rows[0].get("props") or {}
        citations = _rows_to_paths(
            _rows(
                queries.INVESTIGATION_CITATIONS,
                {"investigation_id": investigation_id, "limit": queries.default_limit()},
            )
        )
        cited_nodes: list[NodeRef] = []
        seen: set[str] = set()
        for path in citations:
            for node in path.nodes[1:]:  # skip the investigation node itself
                if node.id not in seen:
                    seen.add(node.id)
                    cited_nodes.append(node)
        return {**props, "cited_entities": cited_nodes}

    def recall_investigations(self, terms: str, limit: int = 3) -> list[dict[str, Any]]:
        """Past investigations whose question overlaps the current one.

        Term matching happens in Python: it is cheap, keeps the Cypher trivial,
        and makes the ranking auditable.
        """
        wanted = set(_WORD_RE.findall(terms.lower()))
        if not wanted:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for item in self.list_investigations(limit=50):
            haystack = set(_WORD_RE.findall((item.get("question") or "").lower()))
            if not haystack:
                continue
            overlap = wanted & haystack
            if not overlap:
                continue
            score = len(overlap) / len(wanted | haystack)
            scored.append((score, item))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [dict(item, relevance=round(score, 3)) for score, item in scored[:limit] if score > 0]

    def clear_investigations(self) -> int:
        """Delete all investigation memory. Dev/test utility only."""
        rows = _rows(queries.CLEAR_INVESTIGATIONS, {})
        return int(rows[0]["deleted"]) if rows else 0