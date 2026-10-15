"""Domain models for the company knowledge graph.

These types are the contract between the graph layer, the agent, and the API.
They deliberately carry *provenance*: every record can point back at the entity
IDs and relationship paths that produced it, which is what makes answers
explainable rather than merely plausible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    """Timezone-aware UTC now, used as the default for every timestamp."""
    return datetime.now(UTC)


class EntityType(StrEnum):
    """The node labels defined by the graph schema."""

    PERSON = "Person"
    SERVICE = "Service"
    PROJECT = "Project"
    INCIDENT = "Incident"
    DECISION = "Decision"
    DOCUMENT = "Document"
    INVESTIGATION = "Investigation"


class RelationType(StrEnum):
    """The relationship types defined by the graph schema."""

    OWNS = "OWNS"
    WORKED_ON = "WORKED_ON"
    USES = "USES"
    DEPENDS_ON = "DEPENDS_ON"
    AFFECTED = "AFFECTED"
    CAUSED_BY = "CAUSED_BY"
    RESOLVED = "RESOLVED"
    AFFECTS = "AFFECTS"
    SUPERSEDES = "SUPERSEDES"
    DESCRIBES = "DESCRIBES"
    SUPPORTS = "SUPPORTS"
    CITED = "CITED"


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------


class BaseEntity(BaseModel):
    """Shared identity for every graph node."""

    id: str
    name: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class Person(BaseEntity):
    """An engineer, manager, or reviewer."""

    role: str = ""
    team: str = ""


class Service(BaseEntity):
    """A deployable system in the company's estate."""

    description: str = ""
    criticality: str = "medium"


class Project(BaseEntity):
    """A body of work that consumed services and people's time."""

    status: str = "unknown"


class Incident(BaseModel):
    """A production incident."""

    id: str
    title: str
    severity: str
    occurred_at: str
    summary: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    """An architecture decision record."""

    id: str
    title: str
    date: str
    rationale: str = ""
    status: str = "accepted"
    properties: dict[str, Any] = Field(default_factory=dict)


class Document(BaseModel):
    """A source document such as a runbook, RFC, or postmortem."""

    id: str
    title: str
    source_type: str = "unknown"
    source_uri: str = ""
    content: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Graph traversal structures
# --------------------------------------------------------------------------


class NodeRef(BaseModel):
    """A node plus enough context to render it in the UI."""

    id: str
    type: EntityType
    name: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @property
    def label(self) -> str:
        """Human-friendly subtitle, e.g. an incident's severity."""
        for key in ("criticality", "severity", "status", "role"):
            if key in self.properties:
                return str(self.properties[key])
        return self.type.value


class Edge(BaseModel):
    """A directed relationship between two nodes."""

    type: RelationType
    from_id: str
    from_type: EntityType
    to_id: str
    to_type: EntityType


class GraphPath(BaseModel):
    """An ordered walk through the graph.

    This is the core explainability artefact: an answer claims something, and
    the path shows *how* the agent got there.
    """

    nodes: list[NodeRef]
    edges: list[Edge]
    explanation: str = ""

    @property
    def length(self) -> int:
        return len(self.edges)

    def signature(self) -> str:
        """Stable key for de-duplicating paths that differ only in explanation."""
        parts = [n.id for n in self.nodes] + [e.type for e in self.edges]
        return "|".join(parts)

    def describe(self) -> str:
        """Render the path as `A -[:DEPENDS_ON]-> B -[:DEPENDS_ON]-> C`."""
        if not self.nodes:
            return ""
        chunks = [self.nodes[0].name or self.nodes[0].id]
        for idx, edge in enumerate(self.edges):
            target = self.nodes[idx + 1]
            chunks.append(f"-[:{edge.type}]-> {target.name or target.id}")
        return " ".join(chunks)


class Evidence(BaseModel):
    """A single retrievable fact, with the provenance needed to audit it.

    `confidence` distinguishes what the graph states outright from what the
    agent inferred. Inferred records must be labelled as such downstream.
    """

    evidence_id: str
    kind: str
    summary: str
    entities: list[NodeRef] = Field(default_factory=list)
    paths: list[GraphPath] = Field(default_factory=list)
    tool: str = ""
    confidence: str = "confirmed"
    source_ids: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


class ImpactedService(BaseModel):
    """A service that a proposed change could affect."""

    service: NodeRef
    depth: int
    owners: list[NodeRef] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    criticality: str = "medium"


class Recommendation(BaseModel):
    """A suggested action - always advisory, never executed."""

    action: str
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    suggested_reviewers: list[NodeRef] = Field(default_factory=list)
    requires_human_approval: bool = True


class ExecutionStep(BaseModel):
    """One observable step of the investigation workflow, surfaced in the UI.

    Lives in the models package rather than the agent package so the API can
    depend on it without importing the agent and creating a cycle.
    """

    node: str
    title: str
    status: Literal["pending", "running", "completed", "skipped", "failed"] = "completed"
    detail: str = ""
    tool: str = ""
    duration_ms: int = 0
    evidence_count: int = 0
    graph_paths: int = 0


class Critique(BaseModel):
    """The critic's verdict on a draft answer."""

    verdict: Literal["pass", "qualify"] = "pass"
    unsupported_claims: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    notes: str = ""