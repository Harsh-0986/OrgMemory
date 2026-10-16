"""Pydantic request and response models for the public API.

These are the documented contract. Every response shape is declared here so the
frontend and the API tests can rely on a stable interface.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.graph import (
    Critique,
    Edge,
    Evidence,
    ExecutionStep,
    GraphPath,
    ImpactedService,
    NodeRef,
    Recommendation,
)

# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    """Machine-readable error body returned for every non-2xx response."""

    code: str = Field(description="Stable machine-readable error code")
    message: str = Field(description="Human-readable explanation")
    detail: str | None = Field(default=None, description="Optional extra context")


class ErrorResponse(BaseModel):
    error: ErrorDetail


# --------------------------------------------------------------------------
# Health / graph
# --------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    app: str
    environment: str
    graph_connected: bool
    graph_name: str
    llm_configured: bool
    version: str
    missing_settings: list[str] = Field(default_factory=list)


class GraphOverviewResponse(BaseModel):
    graph: str
    node_counts: dict[str, int]
    relationship_counts: dict[str, int]
    total_nodes: int
    total_relationships: int
    criticality_breakdown: dict[str, int] = Field(default_factory=dict)


class EntityRecord(BaseModel):
    """One stored entity with its full property set."""

    id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class EntityListResponse(BaseModel):
    """Everything the graph holds for one node label."""

    label: str
    total: int
    search: str = ""
    entities: list[EntityRecord] = Field(default_factory=list)


class FullGraphResponse(BaseModel):
    """Every node and edge in the graph, for the whole-graph view."""

    nodes: list[NodeRef] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)


class NeighborhoodResponse(BaseModel):
    entity_id: str
    depth: int
    nodes: list[NodeRef]
    edges: list[Edge]
    paths: list[GraphPath]


# --------------------------------------------------------------------------
# Investigations
# --------------------------------------------------------------------------


class InvestigationRequest(BaseModel):
    """Body for `POST /api/investigations`."""

    question: str = Field(
        min_length=8,
        max_length=2000,
        description="A natural-language question about the engineering organisation.",
        examples=[
            "Can we replace Payment Service A with Payment Service B? What could "
            "break, who should review it, and why do we use the current service?"
        ],
    )

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned


class InvestigationAccepted(BaseModel):
    """Returned immediately when an investigation is started."""

    investigation_id: str
    question: str
    status: str
    poll_url: str


class InvestigationStatus(BaseModel):
    """Progress of an in-flight or finished job."""

    investigation_id: str
    question: str
    status: str
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None
    done: bool = False
    result: dict[str, Any] | None = None


class InvestigationResponse(BaseModel):
    """Full result of one investigation."""

    investigation_id: str
    question: str
    status: str
    answer: str = ""
    confidence: str = "low"
    intent: str = "explore"
    evidence: list[Evidence] = Field(default_factory=list)
    graph_paths: list[GraphPath] = Field(default_factory=list)
    impacted_services: list[ImpactedService] = Field(default_factory=list)
    owners: dict[str, list[NodeRef]] = Field(default_factory=dict)
    engineers: list[dict[str, Any]] = Field(default_factory=list)
    incidents: list[dict[str, Any]] = Field(default_factory=list)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    shared_dependencies: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    recalled_investigations: list[dict[str, Any]] = Field(default_factory=list)
    critique: Critique | None = None
    steps: list[ExecutionStep] = Field(default_factory=list)
    cited_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class InvestigationSummary(BaseModel):
    """Condensed record used by the history endpoint."""

    id: str
    question: str
    created_at: str | None = None
    summary: str = ""
    cited_ids: list[str] = Field(default_factory=list)


class InvestigationHistoryResponse(BaseModel):
    total: int
    investigations: list[InvestigationSummary]


class InvestigationDetailResponse(BaseModel):
    """A stored investigation, including the entities it cited."""

    id: str
    question: str
    answer: str = ""
    summary: str = ""
    status: str = "completed"
    created_at: str | None = None
    cited_ids: list[str] = Field(default_factory=list)
    cited_entities: list[NodeRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)