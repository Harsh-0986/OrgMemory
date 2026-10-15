"""LangGraph workflow assembly.

The graph is a fixed linear pipeline - no cycles, no self-directed loops:

    plan -> retrieve -> assemble -> write -> critic -> finalize -> memory

Boundedness comes from three independent places: the pipeline has no cycles, the
toolbox caps total tool calls, and `invoke` sets LangGraph's own recursion
limit. Even if a node misbehaves, the run terminates.

The critic sits *after* the writer because a critic needs something to audit;
`finalize` then applies its verdict before the answer is returned and stored.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent import nodes
from app.agent.state import (
    Critique,
    ExecutionStep,
    InvestigationPlan,
    InvestigationState,
    new_state,
)
from app.agent.tools import GraphToolbox
from app.config import get_settings
from app.graph.repository import GraphRepository
from app.models.graph import Evidence

logger = logging.getLogger(__name__)

_compiled: Any | None = None


def finalize_node(state: InvestigationState) -> dict[str, Any]:
    """Apply the critic's verdict to the draft answer.

    A passing answer is returned untouched. A qualified one gains an explicit
    verification section naming the ungrounded claims, so the user sees the
    problem rather than being quietly handed a flawed conclusion.
    """
    critique = Critique(**(state.get("critique") or {}))  # type: ignore[arg-type]
    answer = state.get("answer") or ""

    if critique.verdict == "pass":
        return {"steps": []}

    notes: list[str] = ["\n## Verification notes\n"]
    if critique.unsupported_claims:
        notes.append("The following claims could not be grounded in the graph:\n")
        for claim in critique.unsupported_claims[:6]:
            notes.append(f"- {claim}")
    if critique.contradictions:
        notes.append("\nContradictory evidence was found:\n")
        for item in critique.contradictions[:6]:
            notes.append(f"- {item}")
    if critique.missing_evidence:
        notes.append("\nGaps in the available evidence:\n")
        for gap in critique.missing_evidence[:8]:
            notes.append(f"- {gap}")
    notes.append(
        "\n_Read these as open questions rather than settled findings. Review with "
        "the named owners before acting._"
    )

    return {
        "answer": answer + "\n".join(notes),
        "steps": [
            ExecutionStep(
                node="finalize",
                title="Apply critic verdict",
                status="completed",
                detail=(
                    f"{len(critique.unsupported_claims)} ungrounded claim(s) labelled"
                ),
                tool="finalize",
            )
        ],
    }


def build_graph() -> Any:
    """Construct the compiled LangGraph workflow."""
    workflow = StateGraph(InvestigationState)

    workflow.add_node("plan", nodes.plan_node)
    workflow.add_node("retrieve", nodes.retrieve_node)
    workflow.add_node("assemble", nodes.assemble_evidence_node)
    workflow.add_node("write", nodes.write_node)
    workflow.add_node("critic", nodes.critic_node)
    workflow.add_node("finalize", finalize_node)
    workflow.add_node("memory", nodes.memory_node)

    workflow.add_edge(START, "plan")
    workflow.add_edge("plan", "retrieve")
    workflow.add_edge("retrieve", "assemble")
    workflow.add_edge("assemble", "write")
    workflow.add_edge("write", "critic")
    workflow.add_edge("critic", "finalize")
    workflow.add_edge("finalize", "memory")
    workflow.add_edge("memory", END)

    return workflow.compile()


def get_graph_workflow() -> Any:
    """Cached compiled workflow."""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def run_investigation(
    question: str,
    repository: GraphRepository | None = None,
    investigation_id: str | None = None,
) -> InvestigationState:
    """Run one end-to-end investigation and return the final state.

    Never raises for LLM or graph problems: a failure is recorded in
    `status`/`error` and whatever evidence was gathered is preserved, because a
    partial answer with citations beats a stack trace.
    """
    settings = get_settings()
    repo = repository or GraphRepository()
    investigation_id = investigation_id or nodes.new_investigation_id()

    toolbox = GraphToolbox(repo, budget=settings.agent_max_tool_calls)
    state = new_state(question, investigation_id)
    state["_toolbox"] = toolbox

    try:
        result = get_graph_workflow().invoke(
            state,
            config={
                "recursion_limit": settings.agent_max_recursion,
                "max_concurrency": 4,
            },
        )
        return result  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001 - surfaced through state
        logger.exception("Investigation failed")
        state["status"] = "failed"
        state["error"] = str(exc)
        return state


def summarise_state(state: InvestigationState) -> dict[str, Any]:
    """Condense a final state into the API response shape."""
    plan = InvestigationPlan(**(state.get("plan") or {})) if state.get("plan") else None
    critique = Critique(**(state.get("critique") or {})) if state.get("critique") else None
    evidence: list[Evidence] = state.get("evidence") or []

    return {
        "investigation_id": state.get("investigation_id"),
        "question": state.get("question"),
        "status": state.get("status", "failed"),
        "answer": state.get("answer", ""),
        "confidence": state.get("confidence", "low"),
        "intent": plan.intent if plan else "explore",
        "evidence": evidence,
        "graph_paths": state.get("paths") or [],
        "impacted_services": state.get("impacted") or [],
        "owners": state.get("owners") or {},
        "engineers": state.get("engineers") or [],
        "incidents": state.get("incidents") or [],
        "decisions": state.get("decisions") or [],
        "documents": state.get("documents") or [],
        "shared_dependencies": state.get("shared_dependencies") or [],
        "recommendations": state.get("recommendations") or [],
        "recalled_investigations": state.get("recalled") or [],
        "critique": critique.model_dump() if critique else None,
        "steps": state.get("steps") or [],
        "cited_ids": state.get("cited_ids") or [],
        "error": state.get("error"),
    }