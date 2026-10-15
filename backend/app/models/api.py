"""Pydantic request and response models for the public API.

These are the documented contract. Every response shape is declared here so the
frontend and the API tests can rely on a stable interface.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.graph import (
    Edge,
    Evidence,
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


class ExecutionStepModel(BaseModel):
    node: str
    title: str
    status: str
    detail: str = ""
    tool: str = ""
    duration_ms: int = 0
    evidence_count: int = 0
    graph_paths: int = 0


class CritiqueModel(BaseModel):
    verdict: str
    unsupported_claims: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    notes: str = ""


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
    critique: CritiqueModel | None = None
    steps: list[ExecutionStepModel] = Field(default_factory=list)
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