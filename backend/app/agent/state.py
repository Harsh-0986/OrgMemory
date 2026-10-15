"""Typed agent state for the LangGraph investigation workflow.

Every field here is either an input, a bound, or an artefact with provenance.
`evidence` and `paths` are the spine of the system: the writer may only assert
things that appear in them, and the critic's job is to catch it when it doesn't.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field

from app.models.graph import (
    Critique,
    Evidence,
    ExecutionStep,
    GraphPath,
    ImpactedService,
    NodeRef,
    Recommendation,
)

__all__ = [
    "Critique",
    "ExecutionStep",
    "InvestigationPlan",
    "InvestigationState",
    "QuestionIntent",
    "new_state",
]

QuestionIntent = Literal[
    "replacement",  # "can we swap service X for Y"
    "impact",  # "what breaks if X changes"
    "ownership",  # "who owns X"
    "incident",  # "what happened to X"
    "rationale",  # "why do we use X"
    "explore",  # anything else
]


class InvestigationPlan(BaseModel):
    """Output of the planner node. Constrained to keep retrieval bounded."""

    intent: QuestionIntent = "explore"
    subject_service: str = ""
    comparison_service: str = ""
    focus: list[str] = Field(default_factory=list)
    rationale: str = ""
    uses_llm: bool = False


class InvestigationState(TypedDict, total=False):
    """The state object threaded through every LangGraph node."""

    # -- Input ------------------------------------------------------------
    question: str
    investigation_id: str

    # -- Planning ---------------------------------------------------------
    plan: dict[str, Any]
    resolved_subject: NodeRef | None
    resolved_comparison: NodeRef | None

    # -- Retrieval --------------------------------------------------------
    impacted: list[ImpactedService]
    owners: dict[str, list[NodeRef]]
    engineers: list[dict[str, Any]]
    incidents: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    shared_dependencies: list[dict[str, Any]]
    upstream: dict[str, list[dict[str, Any]]]

    # -- Reasoning --------------------------------------------------------
    evidence: list[Evidence]
    paths: list[GraphPath]
    recalled: list[dict[str, Any]]
    critique: dict[str, Any]
    recommendations: list[Recommendation]
    missing_evidence: list[str]

    # -- Output -----------------------------------------------------------
    answer: str
    confidence: str = "moderate"
    #: Concatenated across nodes by the reducer below. Without it LangGraph
    #: replaces the list on every node and only the final node's steps survive.
    steps: Annotated[list[ExecutionStep], operator.add]

    # -- Bounds / bookkeeping --------------------------------------------
    tool_call_count: int
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    error: str | None
    cited_ids: list[str]

    # -- Injected at construction ------------------------------------------
    #: The toolbox for this run. Carried in state rather than a global so that
    #: concurrent investigations each get their own tool-call budget.
    _toolbox: Any


def new_state(question: str, investigation_id: str) -> InvestigationState:
    """Initial state for a fresh investigation."""
    return InvestigationState(
        question=question,
        investigation_id=investigation_id,
        impacted=[],
        owners={},
        engineers=[],
        incidents=[],
        decisions=[],
        documents=[],
        shared_dependencies=[],
        upstream={},
        evidence=[],
        paths=[],
        recalled=[],
        recommendations=[],
        steps=[],
        tool_call_count=0,
        status="pending",
        cited_ids=[],
    )