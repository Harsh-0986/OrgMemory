"""Allowlisted graph tools with hard execution bounds.

This is the only bridge between the LLM and the database. The model can choose
*which* of these tools to invoke and with what arguments; it can never author
Cypher. Two invariants are enforced here:

1. **Bounded execution.** A shared budget caps total tool calls for a single
   investigation. Once exhausted, tools refuse to run instead of letting a
   confused agent loop.
2. **Provenance.** Every tool returns an `Evidence` record and an
   `ExecutionStep`, so nothing reaches the writer without being attributable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.graph.repository import GraphRepository
from app.models.graph import Evidence, GraphPath, NodeRef

logger = logging.getLogger(__name__)


class BudgetExhausted(RuntimeError):
    """Raised when the per-investigation tool call budget is spent."""


class ToolValidationError(ValueError):
    """Raised when a tool receives arguments it cannot use."""


@dataclass
class ToolResult:
    """What every tool returns: usable data, provenance, and a UI step."""

    data: Any
    evidence: Evidence
    step: dict[str, Any] = field(default_factory=dict)


class GraphToolbox:
    """The allowlisted tool surface, scoped to one investigation."""

    #: Tool names the agent is permitted to request. Anything else is rejected
    #: before it reaches the repository.
    ALLOWED_TOOLS = frozenset(
        {
            "resolve_entity",
            "dependency_impact",
            "owners_of",
            "relevant_engineers",
            "related_incidents",
            "decision_history",
            "supporting_documents",
            "shared_dependencies",
            "upstream_dependencies",
            "recall_investigations",
        }
    )

    def __init__(self, repository: GraphRepository, budget: int | None = None) -> None:
        self.repository = repository
        self.budget = budget or get_settings().agent_max_tool_calls
        self.calls_used = 0

    # -- Budget ------------------------------------------------------------
    def _consume(self, tool: str) -> None:
        if tool not in self.ALLOWED_TOOLS:
            raise ToolValidationError(f"Tool '{tool}' is not in the allowlist")
        if self.calls_used >= self.budget:
            raise BudgetExhausted(
                f"Tool call budget of {self.budget} exhausted during investigation"
            )
        self.calls_used += 1

    @property
    def remaining(self) -> int:
        return max(0, self.budget - self.calls_used)

    def _step(self, node: str, title: str, tool: str, started: float) -> dict[str, Any]:
        return {
            "node": node,
            "title": title,
            "tool": tool,
            "status": "completed",
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }

    # -- Tools -------------------------------------------------------------
    def resolve_entity(self, needle: str) -> ToolResult:
        """Fuzzy-match a service name to a stable service id."""
        started = time.perf_counter()
        self._consume("resolve_entity")
        matches = self.repository.find_services(needle)
        return ToolResult(
            data=matches,
            evidence=Evidence(
                evidence_id="ev-resolve",
                kind="entity_resolution",
                summary=(
                    f"Resolved '{needle}' to "
                    + ", ".join(f"{m.name} ({m.id})" for m in matches)
                    if matches
                    else f"No service in the graph matched '{needle}'"
                ),
                entities=matches,
                tool="resolve_entity",
                confidence="confirmed" if matches else "unknown",
                caveats=[] if matches else ["Entity not found in graph"],
            ),
            step=self._step("planner", f"Resolve '{needle}'", "resolve_entity", started),
        )

    def dependency_impact(self, service_id: str, depth: int | None = None) -> ToolResult:
        """Services that break if `service_id` changes, plus the paths."""
        started = time.perf_counter()
        self._consume("dependency_impact")
        if not service_id:
            raise ToolValidationError("dependency_impact requires a service_id")

        impacted = self.repository.impacted_services(service_id, depth)
        paths = self.repository.dependency_paths(service_id, depth)
        services = [item.service for item in impacted]

        critical = [s for s in services if s.properties.get("criticality") == "critical"]
        summary = (
            f"{len(services)} service(s) depend on {service_id} within "
            f"{get_settings().graph_max_dependency_depth} hops, including "
            f"{len(critical)} critical."
            if services
            else f"Nothing in the graph depends on {service_id}."
        )

        return ToolResult(
            data={"impacted": impacted, "paths": paths},
            evidence=Evidence(
                evidence_id="ev-impact",
                kind="dependency_impact",
                summary=summary,
                entities=services,
                paths=paths,
                tool="dependency_impact",
                source_ids=_unique([s.id for s in services]),
            ),
            step=self._step(
                "retrieve",
                f"Impact analysis for {service_id}",
                "dependency_impact",
                started,
            ),
        )

    def owners_of(self, service_ids: list[str]) -> ToolResult:
        """Who owns each of the given services."""
        started = time.perf_counter()
        self._consume("owners_of")
        owners = self.repository.owners_for(service_ids)
        people: list[NodeRef] = []
        for values in owners.values():
            people.extend(values)

        unowned = [sid for sid in service_ids if sid not in owners]
        return ToolResult(
            data=owners,
            evidence=Evidence(
                evidence_id="ev-owners",
                kind="ownership",
                summary=(
                    f"{len(people)} owner(s) across {len(owners)} service(s)."
                    if owners
                    else "No ownership records found."
                ),
                entities=people,
                tool="owners_of",
                source_ids=_unique([p.id for p in people]),
                caveats=(
                    [f"No owner recorded for: {', '.join(unowned)}"] if unowned else []
                ),
            ),
            step=self._step(
                "retrieve", "Resolve service ownership", "owners_of", started
            ),
        )

    def relevant_engineers(self, service_ids: list[str]) -> ToolResult:
        """People with project or incident history on these services."""
        started = time.perf_counter()
        self._consume("relevant_engineers")
        rows = self.repository.relevant_engineers(service_ids)

        people: dict[str, NodeRef] = {}
        for row in rows:
            people.setdefault(
                row["person_id"],
                NodeRef(
                    id=row["person_id"],
                    type="Person",
                    name=row["person_name"],
                    properties={"role": row.get("person_role", ""), "team": row.get("person_team", "")},
                ),
            )
        return ToolResult(
            data=rows,
            evidence=Evidence(
                evidence_id="ev-engineers",
                kind="relevant_engineers",
                summary=(
                    f"{len(people)} engineer(s) have project or incident history on "
                    f"{'the impacted services' if service_ids else 'these services'}."
                    if rows
                    else "No engineer history recorded for these services."
                ),
                entities=list(people.values()),
                tool="relevant_engineers",
                source_ids=_unique(list(people)),
            ),
            step=self._step(
                "retrieve", "Find engineers with relevant history", "relevant_engineers", started
            ),
        )

    def related_incidents(self, service_ids: list[str]) -> ToolResult:
        """Past incidents affecting these services."""
        started = time.perf_counter()
        self._consume("related_incidents")
        rows = self.repository.related_incidents(service_ids)

        unknowns = [r["id"] for r in rows if not r.get("cause_names")]
        incidents = [
            NodeRef(
                id=r["id"],
                type="Incident",
                name=r.get("title", ""),
                properties={
                    "severity": r.get("severity", ""),
                    "occurred_at": r.get("occurred_at", ""),
                },
            )
            for r in rows
        ]
        return ToolResult(
            data=rows,
            evidence=Evidence(
                evidence_id="ev-incidents",
                kind="related_incidents",
                summary=(
                    f"{len(rows)} related incident(s) found."
                    if rows
                    else "No recorded incidents affect these services."
                ),
                entities=incidents,
                tool="related_incidents",
                source_ids=_unique([i.id for i in incidents]),
                caveats=(
                    [f"No recorded cause for: {', '.join(unknowns)}"] if unknowns else []
                ),
            ),
            step=self._step(
                "retrieve", "Retrieve related incidents", "related_incidents", started
            ),
        )

    def decision_history(self, service_ids: list[str]) -> ToolResult:
        """Architecture decisions affecting these services."""
        started = time.perf_counter()
        self._consume("decision_history")
        rows = self.repository.decision_history(service_ids)

        superseded = [
            r for r in rows if r.get("superseded_by_titles") and r.get("superseded_by_titles") != [None]
        ]
        decisions = [
            NodeRef(
                id=r["id"],
                type="Decision",
                name=r.get("title", ""),
                properties={"date": r.get("date", ""), "status": r.get("status", "")},
            )
            for r in rows
        ]
        return ToolResult(
            data=rows,
            evidence=Evidence(
                evidence_id="ev-decisions",
                kind="decision_history",
                summary=(
                    f"{len(rows)} architecture decision(s) apply."
                    if rows
                    else "No architecture decisions recorded for these services."
                ),
                entities=decisions,
                tool="decision_history",
                source_ids=_unique([d.id for d in decisions]),
                caveats=(
                    [f"Superseded: {len(superseded)} decision(s)"] if superseded else []
                ),
            ),
            step=self._step(
                "retrieve", "Retrieve architecture decisions", "decision_history", started
            ),
        )

    def supporting_documents(self, entity_ids: list[str]) -> ToolResult:
        """Documents describing or supporting the given entities."""
        started = time.perf_counter()
        self._consume("supporting_documents")
        rows = self.repository.supporting_documents(entity_ids)
        docs = [
            NodeRef(
                id=r["id"],
                type="Document",
                name=r.get("title", ""),
                properties={
                    "source_type": r.get("source_type", ""),
                    "source_uri": r.get("source_uri", ""),
                },
            )
            for r in rows
        ]
        return ToolResult(
            data=rows,
            evidence=Evidence(
                evidence_id="ev-documents",
                kind="supporting_documents",
                summary=(
                    f"{len(rows)} supporting document(s) found."
                    if rows
                    else "No supporting documents are linked to these entities."
                ),
                entities=docs,
                tool="supporting_documents",
                source_ids=_unique([d.id for d in docs]),
            ),
            step=self._step(
                "retrieve", "Retrieve supporting documents", "supporting_documents", started
            ),
        )

    def shared_dependencies(self, service_a: str, service_b: str) -> ToolResult:
        """Dependencies shared by two services - the joint migration risk surface."""
        started = time.perf_counter()
        self._consume("shared_dependencies")
        if not (service_a and service_b):
            raise ToolValidationError("shared_dependencies requires two service ids")
        rows = self.repository.shared_dependencies(service_a, service_b)
        deps = [_service_node(r) for r in rows]
        return ToolResult(
            data=rows,
            evidence=Evidence(
                evidence_id="ev-shared",
                kind="shared_dependencies",
                summary=(
                    f"{len(rows)} shared dependency/dependencies between {service_a} and {service_b}."
                    if rows
                    else "The two services share no recorded dependencies."
                ),
                entities=deps,
                tool="shared_dependencies",
                source_ids=_unique([d.id for d in deps]),
                confidence="confirmed" if rows else "unknown",
            ),
            step=self._step(
                "retrieve",
                f"Compare dependencies of {service_a} and {service_b}",
                "shared_dependencies",
                started,
            ),
        )

    def upstream_dependencies(self, service_id: str, depth: int | None = None) -> ToolResult:
        """What a service itself depends on."""
        started = time.perf_counter()
        self._consume("upstream_dependencies")
        rows = self.repository.upstream_dependencies(service_id, depth)
        deps = [_service_node(r) for r in rows]
        return ToolResult(
            data=rows,
            evidence=Evidence(
                evidence_id="ev-upstream",
                kind="upstream_dependencies",
                summary=(
                    f"{service_id} depends on {len(rows)} upstream service(s)."
                    if rows
                    else f"{service_id} has no recorded dependencies."
                ),
                entities=deps,
                tool="upstream_dependencies",
                source_ids=_unique([d.id for d in deps]),
            ),
            step=self._step(
                "retrieve",
                f"Upstream dependencies of {service_id}",
                "upstream_dependencies",
                started,
            ),
        )

    def recall_investigations(self, question: str, limit: int = 3) -> ToolResult:
        """Past investigations whose question overlaps the current one."""
        started = time.perf_counter()
        self._consume("recall_investigations")
        rows = self.repository.recall_investigations(question, limit)
        return ToolResult(
            data=rows,
            evidence=Evidence(
                evidence_id="ev-recall",
                kind="previous_investigations",
                summary=(
                    f"{len(rows)} related past investigation(s) found."
                    if rows
                    else "No related past investigations were found for this question."
                ),
                tool="recall_investigations",
                source_ids=_unique([r["id"] for r in rows]),
                confidence="confirmed" if rows else "unknown",
            ),
            step=self._step(
                "recall", "Recall previous investigations", "recall_investigations", started
            ),
        )


def _unique(ids: list[str]) -> list[str]:
    """Order-preserving de-duplication.

    Graph queries that traverse a join (an incident per affected service, a
    document per related entity) return the same id more than once. Those rows
    are meaningful — the UI shows which entity each relates to — but the
    `source_ids` list rendered as chips must not repeat, or React sees duplicate
    keys.
    """
    return list(dict.fromkeys(i for i in ids if i))


def _service_node(row: dict[str, Any]) -> NodeRef:
    """Build a service `NodeRef` from a repository row."""
    return NodeRef(
        id=row.get("id", ""),
        type="Service",
        name=row.get("name", ""),
        properties={
            "description": row.get("description", ""),
            "criticality": row.get("criticality", "medium"),
        },
    )


def dedupe_paths(paths: list[GraphPath]) -> list[GraphPath]:
    """Module-level helper so nodes can share the repository's dedupe rule."""
    seen: set[str] = set()
    unique: list[GraphPath] = []
    for path in paths:
        key = path.signature()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique