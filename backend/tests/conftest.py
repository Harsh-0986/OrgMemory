"""Shared test fixtures.

The centrepiece is `FakeGraphRepository`: an in-memory implementation of the
same interface as `GraphRepository`, backed by the real seed dataset. That lets
the whole LangGraph pipeline run deterministically in tests with no database and
no LLM, while the live-database tests (marked `integration`) still exercise the
actual Cypher when credentials are available.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import pytest

from app.seed import data


class FakeGraphRepository:
    """In-memory stand-in for `GraphRepository`, backed by the seed dataset.

    It reproduces the same semantics the Cypher implements - most importantly
    the reverse traversal used for impact analysis - so a test that passes here
    is testing real behaviour, not a stub that agrees with itself.
    """

    def __init__(self) -> None:
        self.services = {s["id"]: s for s in data.SERVICES}
        self.people = {p["id"]: p for p in data.PEOPLE}
        self.incidents = {i["id"]: i for i in data.INCIDENTS}
        self.decisions = {d["id"]: d for d in data.DECISIONS}
        self.documents = {d["id"]: d for d in data.DOCUMENTS}
        self.projects = {p["id"]: p for p in data.PROJECTS}

        # impact[dependency] = everything that depends on it
        self.impact: dict[str, list[str]] = defaultdict(list)
        self.dependencies: dict[str, list[str]] = defaultdict(list)
        for src, rel, dst in data.DEPENDENCIES:
            if rel == "DEPENDS_ON":
                self.impact[dst].append(src)
                self.dependencies[src].append(dst)

        self.owners: dict[str, list[str]] = defaultdict(list)
        for person, _, svc in data.OWNERSHIP:
            self.owners[svc].append(person)

        self.project_work: dict[str, list[str]] = defaultdict(list)
        for person, _, proj in data.PROJECT_WORK:
            self.project_work[person].append(proj)

        self.project_uses: dict[str, list[str]] = defaultdict(list)
        for proj, _, svc in data.PROJECT_USAGE:
            self.project_uses[proj].append(svc)

        self.incident_affected: dict[str, list[str]] = defaultdict(list)
        for inc, _, svc in data.INCIDENT_AFFECTED:
            self.incident_affected[svc].append(inc)

        self.incident_cause: dict[str, list[str]] = defaultdict(list)
        for inc, _, svc in data.INCIDENT_CAUSE:
            self.incident_cause[inc].append(svc)

        self.resolvers: dict[str, list[str]] = defaultdict(list)
        for person, _, inc in data.INCIDENT_RESOLVER:
            self.resolvers[inc].append(person)

        self.decision_affects: dict[str, list[str]] = defaultdict(list)
        for dec, _, svc in data.DECISION_AFFECTS:
            self.decision_affects[svc].append(dec)

        self.superseded_by: dict[str, list[str]] = defaultdict(list)
        for new, _, old in data.DECISION_SUPERSEDES:
            self.superseded_by[old].append(new)

        self.doc_describes: dict[str, list[str]] = defaultdict(list)
        self.doc_supports: dict[str, list[str]] = defaultdict(list)
        for doc, _, svc in data.DOCUMENT_DESCRIBES:
            self.doc_describes[svc].append(doc)
        for doc, _, dec in data.DOCUMENT_SUPPORTS:
            self.doc_supports[dec].append(doc)

        self.investigations: dict[str, dict[str, Any]] = {}
        self.cited_links: dict[str, list[str]] = defaultdict(list)

    # -- Entity resolution -------------------------------------------------
    def all_services(self) -> list[dict[str, Any]]:
        return list(self.services.values())

    def find_services(self, needle: str) -> list[Any]:
        from app.graph.repository import _service_ref

        if not needle or not needle.strip():
            return []
        text = needle.strip().lower()
        return [
            _service_ref(s)
            for s in self.services.values()
            if text in s["name"].lower() or text in s["id"].lower()
            or text in s.get("description", "").lower()
        ]

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        for table, label in (
            (self.services, "Service"),
            (self.people, "Person"),
            (self.incidents, "Incident"),
            (self.decisions, "Decision"),
            (self.documents, "Document"),
            (self.projects, "Project"),
        ):
            if entity_id in table:
                return {"id": entity_id, "label": label, "properties": table[entity_id]}
        if entity_id in self.investigations:
            return {
                "id": entity_id,
                "label": "Investigation",
                "properties": self.investigations[entity_id],
            }
        return None

    # -- Dependency analysis ------------------------------------------------
    def impacted_services(self, service_id: str, depth: int | None = None) -> list[Any]:
        from app.graph.repository import _as_node_ref
        from app.models.graph import EntityType, ImpactedService

        limit = depth or 3
        seen: dict[str, int] = {}
        queue: deque[tuple[str, int]] = deque([(service_id, 0)])
        while queue:
            node, d = queue.popleft()
            if d >= limit:
                continue
            for dependent in self.impact.get(node, []):
                if dependent not in seen:
                    seen[dependent] = d + 1
                    queue.append((dependent, d + 1))

        owners = self.owners_for(list(seen))
        results = []
        for svc_id, hops in sorted(seen.items(), key=lambda kv: (kv[1], kv[0])):
            svc = self.services[svc_id]
            results.append(
                ImpactedService(
                    service=_as_node_ref(
                        svc_id,
                        EntityType.SERVICE.value,
                        svc["name"],
                        description=svc.get("description", ""),
                        criticality=svc.get("criticality", "medium"),
                        tier=svc.get("tier", ""),
                    ),
                    depth=hops,
                    owners=owners.get(svc_id, []),
                    reasons=[f"Depends on the changed service through {hops} dependency hop(s)."],
                    criticality=svc.get("criticality", "medium"),
                )
            )
        return results

    def dependency_paths(self, service_id: str, depth: int | None = None) -> list[Any]:
        from app.models.graph import Edge, EntityType, GraphPath, NodeRef, RelationType

        limit = depth or 3
        paths: list[GraphPath] = []

        def walk(current: str, chain: list[str], hops: int) -> None:
            if hops >= limit:
                return
            for dependent in self.impact.get(current, []):
                if dependent in chain:
                    continue
                nodes = [
                    NodeRef(
                        id=nid,
                        type=EntityType.SERVICE,
                        name=self.services[nid]["name"],
                    )
                    for nid in [*chain, dependent]
                ]
                edges = [
                    Edge(
                        type=RelationType.DEPENDS_ON,
                        from_id=src.id,
                        from_type=EntityType.SERVICE,
                        to_id=dst.id,
                        to_type=EntityType.SERVICE,
                    )
                    for src, dst in zip(nodes, nodes[1:], strict=False)
                ]
                paths.append(
                    GraphPath(
                        nodes=nodes,
                        edges=edges,
                        explanation=f"{hops + 1}-hop path",
                    )
                )
                walk(dependent, [*chain, dependent], hops + 1)

        walk(service_id, [service_id], 0)
        return paths

    def upstream_dependencies(self, service_id: str, depth: int | None = None) -> list[dict[str, Any]]:
        rows = []
        for dep in self.dependencies.get(service_id, []):
            svc = self.services[dep]
            rows.append(
                {
                    "id": dep,
                    "name": svc["name"],
                    "description": svc.get("description", ""),
                    "criticality": svc.get("criticality", "medium"),
                    "depth": 1,
                }
            )
        return rows

    def shared_dependencies(self, service_a: str, service_b: str) -> list[dict[str, Any]]:
        deps_b = set(self.dependencies.get(service_b, []))
        out = []
        for dep in self.dependencies.get(service_a, []):
            if dep in deps_b:
                svc = self.services[dep]
                out.append(
                    {
                        "id": dep,
                        "name": svc["name"],
                        "description": svc.get("description", ""),
                        "criticality": svc.get("criticality", "medium"),
                    }
                )
        return out

    # -- People -------------------------------------------------------------
    def owners_for(self, service_ids: list[str]) -> dict[str, list[Any]]:
        from app.graph.repository import _person_ref

        out: dict[str, list[Any]] = {}
        for sid in dict.fromkeys(service_ids):
            people = [
                _person_ref(
                    {
                        "person_id": pid,
                        "person_name": self.people[pid]["name"],
                        "person_role": self.people[pid].get("role", ""),
                        "person_team": self.people[pid].get("team", ""),
                    }
                )
                for pid in self.owners.get(sid, [])
            ]
            if people:
                out[sid] = people
        return out

    def relevant_engineers(self, service_ids: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for sid in dict.fromkeys(service_ids):
            for proj_id, used in self.project_uses.items():
                if sid not in used:
                    continue
                for pid in self.project_work.get(proj_id, []):
                    rows.append(
                        {
                            "person_id": pid,
                            "person_name": self.people[pid]["name"],
                            "person_role": self.people[pid].get("role", ""),
                            "person_team": self.people[pid].get("team", ""),
                            "project_id": proj_id,
                            "project_name": self.projects[proj_id]["name"],
                            "project_status": self.projects[proj_id].get("status", ""),
                            "service_id": sid,
                            "service_name": self.services[sid]["name"],
                            "reason": "project",
                        }
                    )
            for inc_id in self.incident_affected.get(sid, []):
                for pid in self.resolvers.get(inc_id, []):
                    rows.append(
                        {
                            "person_id": pid,
                            "person_name": self.people[pid]["name"],
                            "person_role": self.people[pid].get("role", ""),
                            "person_team": self.people[pid].get("team", ""),
                            "project_id": inc_id,
                            "project_name": self.incidents[inc_id]["title"],
                            "project_status": self.incidents[inc_id].get("severity", ""),
                            "service_id": sid,
                            "service_name": self.services[sid]["name"],
                            "reason": "incident",
                        }
                    )
        return rows

    # -- Incidents / decisions / documents ----------------------------------
    def related_incidents(self, service_ids: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for sid in dict.fromkeys(service_ids):
            for inc_id in self.incident_affected.get(sid, []):
                inc = self.incidents[inc_id]
                causes = [self.services[c]["name"] for c in self.incident_cause.get(inc_id, [])]
                rows.append(
                    {
                        "id": inc_id,
                        "title": inc["title"],
                        "severity": inc["severity"],
                        "occurred_at": inc["occurred_at"],
                        "summary": inc.get("summary", ""),
                        "root_cause_known": inc.get("root_cause_known"),
                        "service_id": sid,
                        "service_name": self.services[sid]["name"],
                        "cause_ids": [c for c in self.incident_cause.get(inc_id, [])],
                        "cause_names": causes,
                        "resolver_ids": self.resolvers.get(inc_id, []),
                        "resolver_names": [self.people[p]["name"] for p in self.resolvers.get(inc_id, [])],
                    }
                )
        return sorted(rows, key=lambda r: r["occurred_at"], reverse=True)

    def decision_history(self, service_ids: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for sid in dict.fromkeys(service_ids):
            for dec_id in self.decision_affects.get(sid, []):
                dec = self.decisions[dec_id]
                superseding = self.superseded_by.get(dec_id, [])
                rows.append(
                    {
                        "id": dec_id,
                        "title": dec["title"],
                        "date": dec["date"],
                        "rationale": dec.get("rationale", ""),
                        "status": dec.get("status", ""),
                        "service_id": sid,
                        "service_name": self.services[sid]["name"],
                        "superseded_by_ids": superseding,
                        "superseded_by_titles": [self.decisions[s]["title"] for s in superseding],
                    }
                )
        return sorted(rows, key=lambda r: r["date"], reverse=True)

    def supporting_documents(self, entity_ids: list[str]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for eid in dict.fromkeys(entity_ids):
            targets = [(d, "DESCRIBES") for d in self.doc_describes.get(eid, [])]
            targets += [(d, "SUPPORTS") for d in self.doc_supports.get(eid, [])]
            for doc_id, rel in targets:
                doc = self.documents[doc_id]
                entity = self.get_entity(eid)
                rows.append(
                    {
                        "id": doc_id,
                        "title": doc["title"],
                        "source_type": doc.get("source_type", ""),
                        "source_uri": doc.get("source_uri", ""),
                        "content": doc.get("content", ""),
                        "entity_id": eid,
                        "entity_name": (entity or {}).get("properties", {}).get("name")
                        or (entity or {}).get("properties", {}).get("title", ""),
                        "entity_label": (entity or {}).get("label", ""),
                        "relation_type": rel,
                    }
                )
        return rows

    # -- Memory -------------------------------------------------------------
    def save_investigation(self, **kwargs: Any) -> str:
        inv_id = kwargs["investigation_id"]
        self.investigations[inv_id] = {
            "id": inv_id,
            "question": kwargs.get("question", ""),
            "answer": kwargs.get("answer", ""),
            "summary": kwargs.get("summary", ""),
            "status": kwargs.get("status", "completed"),
            "cited_ids": list(kwargs.get("cited_ids") or []),
            "metadata": kwargs.get("metadata") or {},
            "created_at": "2026-01-01T00:00:00+00:00",
        }
        self.cited_links[inv_id] = [
            c for c in (kwargs.get("cited_ids") or []) if self.get_entity(c)
        ]
        return inv_id

    def list_investigations(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(list(self.investigations.values())))[:limit]

    def get_investigation(self, investigation_id: str) -> dict[str, Any] | None:
        record = self.investigations.get(investigation_id)
        if not record:
            return None
        from app.graph.repository import _as_node_ref

        cited = []
        for cid in self.cited_links.get(investigation_id, []):
            entity = self.get_entity(cid)
            if entity:
                props = entity["properties"]
                cited.append(
                    _as_node_ref(
                        cid,
                        entity["label"],
                        props.get("name") or props.get("title", ""),
                    )
                )
        return {**record, "cited_entities": cited}

    def recall_investigations(self, terms: str, limit: int = 3) -> list[dict[str, Any]]:
        from app.graph.repository import rank_investigations

        return rank_investigations(self.list_investigations(limit=50), terms, limit)

    def clear_investigations(self) -> int:
        count = len(self.investigations)
        self.investigations.clear()
        self.cited_links.clear()
        return count

    def overview(self) -> dict[str, Any]:
        from collections import Counter

        rel_counts = Counter(rel for _, rel, _ in data.all_relationships())
        return {
            "graph": "fake",
            "node_counts": {
                "Person": len(self.people),
                "Service": len(self.services),
                "Project": len(self.projects),
                "Incident": len(self.incidents),
                "Decision": len(self.decisions),
                "Document": len(self.documents),
            },
            "relationship_counts": dict(rel_counts),
            "total_nodes": sum(
                [len(self.people), len(self.services), len(self.projects),
                 len(self.incidents), len(self.decisions), len(self.documents)]
            ),
            "total_relationships": sum(rel_counts.values()),
            "criticality_breakdown": dict(
                Counter(s.get("criticality", "unknown") for s in self.services.values())
            ),
        }

    def neighborhood(self, entity_id: str, depth: int | None = None) -> dict[str, Any]:
        return {"entity_id": entity_id, "depth": depth or 3, "nodes": [], "edges": [], "paths": []}


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def fake_repo() -> FakeGraphRepository:
    """A fresh in-memory repository for each test."""
    return FakeGraphRepository()


@pytest.fixture
def graph_available() -> bool:
    """True only when a real FalkorDB instance is reachable and seeded."""
    from app.graph import client as graph_client

    if not graph_client.ping():
        return False
    try:
        rows = graph_client.get_graph().query("MATCH (s:Service) RETURN count(s) AS c")
        return bool(rows.result_set and rows.result_set[0][0])
    except Exception:
        return False


@pytest.fixture
def integration(graph_available: bool) -> None:
    """Skip a test unless a seeded FalkorDB instance is available."""
    if not graph_available:
        pytest.skip("FalkorDB not reachable or graph not seeded")