"""LangGraph node implementations.

Each LLM-backed node has a deterministic fallback. That is deliberate: the demo
must not collapse if the model endpoint rate-limits, and the grounding guarantees
must hold in tests without spending tokens.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from app.agent.prompts import (
    CRITIC_SYSTEM,
    CRITIC_USER,
    PLANNER_SYSTEM,
    PLANNER_USER,
    WRITER_SYSTEM,
    WRITER_USER,
)
from app.agent.state import Critique, ExecutionStep, InvestigationPlan, InvestigationState
from app.agent.tools import BudgetExhausted, GraphToolbox, ToolValidationError
from app.config import get_settings
from app.llm import LLMUnavailable, get_llm
from app.models.graph import Evidence, NodeRef, Recommendation

logger = logging.getLogger(__name__)

#: Keywords used by the heuristic intent classifier.
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "replacement": ("replace", "swap", "migrate", "switch", "move off", "instead of", "cut over"),
    "impact": ("impact", "break", "blast radius", "downstream", "goes down", "what depends"),
    "ownership": ("who owns", "owner", "who should", "review", "responsible", "on-call"),
    "incident": ("incident", "outage", "postmortem", "broke", "failed", "root cause"),
    "rationale": ("why", "rationale", "decided", "chosen", "reason", "trade-off", "tradeoff"),
}

#: Patterns that name two services and their order, subject first.
#: The capture classes are bounded so a lazy quantifier cannot stop mid-word
#: at the end of a sentence ("...with Payment Service B?" must capture the
#: whole name, not just "p").
_PAIR_PATTERNS = (
    r"replace\s+(?P<subject>[^?!.]+?)\s+with\s+(?P<comparison>[^?!.,]+)",
    r"replace\s+(?P<subject>[^?!.]+?)\s+by\s+(?P<comparison>[^?!.,]+)",
    r"swap\s+(?P<subject>[^?!.]+?)\s+for\s+(?P<comparison>[^?!.,]+)",
    r"switch\s+from\s+(?P<subject>[^?!.]+?)\s+to\s+(?P<comparison>[^?!.,]+)",
    r"move\s+from\s+(?P<subject>[^?!.]+?)\s+to\s+(?P<comparison>[^?!.,]+)",
    r"migrate\s+from\s+(?P<subject>[^?!.]+?)\s+to\s+(?P<comparison>[^?!.,]+)",
    r"use\s+(?P<comparison>[^?!.,]+?)\s+instead\s+of\s+(?P<subject>[^?!.]+)",
)

_CITATION_RE = re.compile(r"\[([a-z]+-[a-z0-9\-]+)\]", re.IGNORECASE)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _service_aliases(service: dict[str, Any]) -> list[str]:
    """Lowercase search aliases for a service, longest-first."""
    name = service.get("name", "")
    core = name.split(" (")[0].strip()
    aliases = {core.lower(), service.get("id", "").lower()}
    if " (" in name:
        aliases.add(name.split(" (", 1)[1].rstrip(")").lower())
    return sorted((a for a in aliases if len(a) > 3), key=len, reverse=True)


def match_services(question: str, services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find services mentioned in a question, ordered by first mention.

    Longest-alias-wins matching prevents "Payment Service" from shadowing the
    more specific "Payment Service A".
    """
    text = f" {question.lower()} "
    hits: list[tuple[int, dict[str, Any]]] = []
    for service in services:
        best: tuple[int, str] | None = None
        for alias in _service_aliases(service):
            pos = text.find(alias)
            if pos != -1 and (best is None or len(alias) > best[1]):
                best = (pos, alias)
        if best:
            hits.append((best[0], service))
    hits.sort(key=lambda pair: pair[0])
    return [service for _, service in hits]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull a JSON object out of a model response, tolerating prose around it."""
    if not text:
        return None
    import json

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-z]*\n?|```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    match = _JSON_RE.search(cleaned)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


def _invoke(system: str, user: str, timeout: float) -> str:
    """Call the chat model and return plain text. Never raises."""
    try:
        llm = get_llm()
        response = llm.invoke(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        return str(getattr(response, "content", response) or "")
    except (LLMUnavailable, Exception) as exc:  # noqa: BLE001 - fallback path
        logger.warning("LLM call failed, falling back: %s", exc)
        return ""


# --------------------------------------------------------------------------
# Node 1 - Planner
# --------------------------------------------------------------------------


def plan_node(state: InvestigationState) -> dict[str, Any]:
    """Classify the question and resolve any services it names."""
    started = time.perf_counter()
    _phase(state, "plan", "Understanding the question")
    question = state["question"]
    toolbox: GraphToolbox = state["_toolbox"]  # type: ignore[index]
    repo = toolbox.repository

    services = repo.all_services()

    llm_plan: dict[str, Any] | None = None
    catalogue = ", ".join(s.get("name", "") for s in services) or "(none recorded)"
    raw = _invoke(
        PLANNER_SYSTEM,
        PLANNER_USER.format(question=question, services=catalogue),
        timeout=get_settings().agent_query_timeout_seconds,
    )
    if raw:
        llm_plan = _extract_json(raw)

    plan = _merge_plan(question, services, llm_plan)

    steps: list[ExecutionStep] = [
        ExecutionStep(
            node="plan",
            title="Classify question and choose strategy",
            status="completed",
            detail=f"Intent: {plan.intent}"
            + (f" · resolved by {'LLM + ' if plan.uses_llm else ''}rules"
               if plan.uses_llm else " (no model available)"),
            tool="planner",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    ]

    # Resolve the named services to stable ids via the allowlisted tool.
    resolved_subject: NodeRef | None = None
    resolved_comparison: NodeRef | None = None
    try:
        if plan.subject_service:
            result = toolbox.resolve_entity(plan.subject_service)
            if result.data:
                resolved_subject = result.data[0]
                steps.append(
                    ExecutionStep(
                        **{
                            **result.step,
                            "evidence_count": len(result.evidence.entities),
                        }
                    )
                )
        if plan.comparison_service:
            result = toolbox.resolve_entity(plan.comparison_service)
            if result.data:
                resolved_comparison = result.data[0]
                steps.append(
                    ExecutionStep(
                        **{
                            **result.step,
                            "evidence_count": len(result.evidence.entities),
                        }
                    )
                )
    except (BudgetExhausted, ToolValidationError) as exc:
        logger.warning("Entity resolution skipped: %s", exc)

    if not plan.subject_service and services:
        logger.info("Planner could not identify a subject service for: %s", question)

    return {
        "plan": plan.model_dump(),
        "resolved_subject": resolved_subject,
        "resolved_comparison": resolved_comparison,
        "steps": steps,
        "tool_call_count": toolbox.calls_used,
    }


def snap_to_service(phrase: str, services: list[dict[str, Any]]) -> str:
    """Normalise an extracted phrase to a canonical service name.

    Phrases lifted out of a sentence carry articles and trailing clauses
    ("the checkout api", "payment service a for checkout"). Matching is a plain
    CONTAINS in the graph, so those fragments would resolve to nothing. This
    snaps them onto the closest real alias and returns its canonical name.
    """
    if not phrase:
        return ""
    cleaned = re.sub(r"^(the|a|an|our)\s+", "", phrase.strip().lower()).strip()
    if not cleaned:
        return ""

    best_name = ""
    best_len = 0
    for service in services:
        for alias in _service_aliases(service):
            if alias in cleaned or cleaned in alias:
                if len(alias) > best_len:
                    best_len = len(alias)
                    best_name = service.get("name", "")
    return best_name or phrase.strip()


def _merge_plan(
    question: str,
    services: list[dict[str, Any]],
    llm_plan: dict[str, Any] | None,
) -> InvestigationPlan:
    """Combine model output with rule-based detection, rules winning on conflict."""
    text = question.lower()
    heuristic_intent = "explore"
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            heuristic_intent = intent
            break

    matched = match_services(question, services)
    subject_guess = ""
    comparison_guess = ""

    for pattern in _PAIR_PATTERNS:
        match = re.search(pattern, text)
        if not match:
            continue
        groups = match.groupdict()
        subject_guess = groups.get("subject", "") or ""
        comparison_guess = groups.get("comparison", "") or ""
        break

    if not subject_guess and matched:
        subject_guess = matched[0].get("name", "")
    if not comparison_guess and len(matched) > 1:
        comparison_guess = matched[1].get("name", "")

    plan = InvestigationPlan(
        intent=heuristic_intent,
        subject_service=subject_guess,
        comparison_service=comparison_guess,
        rationale="Deterministic intent and entity detection.",
    )

    if llm_plan:
        intent = llm_plan.get("intent")
        if intent in _INTENT_KEYWORDS:
            plan.intent = intent  # type: ignore[assignment]
        # Prefer the LLM's entity choice only when the rules found nothing, so a
        # hallucinated service name can never override a grounded match.
        if not plan.subject_service:
            plan.subject_service = str(llm_plan.get("subject_service") or "")
        if not plan.comparison_service:
            plan.comparison_service = str(llm_plan.get("comparison_service") or "")
        focus = llm_plan.get("focus")
        if isinstance(focus, list):
            plan.focus = [str(f) for f in focus][:6]
        plan.rationale = str(llm_plan.get("rationale") or plan.rationale)
        plan.uses_llm = True

    if not plan.focus:
        plan.focus = ["impact", "ownership", "evidence"]

    # Snap whatever we extracted onto canonical service names.
    plan.subject_service = snap_to_service(plan.subject_service, services)
    plan.comparison_service = snap_to_service(plan.comparison_service, services)
    if plan.subject_service == plan.comparison_service:
        plan.comparison_service = ""
    return plan


# --------------------------------------------------------------------------
# Node 2 - Graph Retriever
# --------------------------------------------------------------------------


def _report(state: InvestigationState, step: ExecutionStep) -> None:
    """Publish a step to whoever is watching (an async job, or nothing).

    Progress is emitted as the workflow runs rather than collected at the end,
    so an async caller can show where the agent has got to. Failures here are
    swallowed: progress reporting must never affect the investigation.
    """
    reporter = state.get("_progress")
    if reporter is None:
        return
    try:
        reporter(step)
    except Exception:  # noqa: BLE001 - progress is best-effort
        logger.debug("Progress reporter failed", exc_info=True)


def _phase(
    state: InvestigationState,
    node: str,
    title: str,
    detail: str = "",
) -> None:
    """Announce that a workflow phase has begun.

    Only reported, never stored: this is a transient "what is happening right
    now" signal for a polling client. The durable trace is the ExecutionStep
    each node appends to `steps`, so adding these to state would double-count.

    The phases that matter most are the ones wrapped around a model call - they
    are the slowest part of a run, and without this the dashboard would sit
    frozen on the last tool call while the writer thinks.
    """
    _report(
        state,
        ExecutionStep(node=node, title=title, status="running", detail=detail),
    )


def _safe_tool(
    toolbox: GraphToolbox,
    evidence: list[Evidence],
    steps: list[ExecutionStep],
    state: InvestigationState | None,
    tool_name: str,
    **kwargs: Any,
) -> Any:
    """Run one allowlisted tool, recording a step even when it is skipped.

    A budget-exhausted or invalid call becomes a visible `skipped` step rather
    than an exception, so the UI shows the agent was bounded instead of broken.
    """
    method = getattr(toolbox, tool_name)
    try:
        result = method(**kwargs)
    except BudgetExhausted as exc:
        step = ExecutionStep(
            node="retrieve",
            title=f"{tool_name} (budget exhausted)",
            status="skipped",
            detail=str(exc),
            tool=tool_name,
        )
        steps.append(step)
        if state is not None:
            _report(state, step)
        return None
    except (ToolValidationError, Exception) as exc:  # noqa: BLE001 - surfaced as a step
        logger.warning("Tool %s failed: %s", tool_name, exc)
        step = ExecutionStep(
            node="retrieve",
            title=f"{tool_name} (failed)",
            status="failed",
            detail=str(exc),
            tool=tool_name,
        )
        steps.append(step)
        if state is not None:
            _report(state, step)
        return None

    evidence.append(result.evidence)
    step = ExecutionStep(
        **result.step,
        evidence_count=len(result.evidence.entities),
        graph_paths=len(result.evidence.paths),
    )
    steps.append(step)
    if state is not None:
        _report(state, step)
    return result


def retrieve_node(state: InvestigationState) -> dict[str, Any]:
    """Run the allowlisted query set implied by the plan."""
    _phase(state, "retrieve", "Querying the knowledge graph")
    toolbox: GraphToolbox = state["_toolbox"]  # type: ignore[index]
    plan = InvestigationPlan(**state["plan"])  # type: ignore[arg-type]
    subject = state.get("resolved_subject")
    comparison = state.get("resolved_comparison")

    evidence: list[Evidence] = []
    steps: list[ExecutionStep] = []

    updates: dict[str, Any] = {}

    # -- Always try to recall earlier investigations ------------------------
    recall = _safe_tool(
        toolbox, evidence, steps, state, "recall_investigations", question=state["question"]
    )
    updates["recalled"] = (recall.data if recall else []) or []

    # -- Everything below needs a resolved subject service ------------------
    if not subject:
        steps.append(
            ExecutionStep(
                node="retrieve",
                title="Graph retrieval skipped",
                status="skipped",
                detail=(
                    "No service could be resolved from the question, so dependency, "
                    "ownership and incident queries were not run."
                ),
            )
        )
        updates.update({"evidence": evidence, "steps": steps, "tool_call_count": toolbox.calls_used})
        return updates

    subject_id = subject.id

    # The planner's intent decides which queries are worth spending budget on.
    # An ownership question has no need for full incident history, and a
    # rationale question is mostly decisions and documents.
    intent = plan.intent
    wants_impact = intent in ("replacement", "impact", "explore")
    wants_ownership = intent in ("replacement", "ownership", "impact", "explore")
    wants_incidents = intent in ("replacement", "impact", "incident", "explore")
    wants_decisions = intent in ("replacement", "rationale", "explore")

    impacted: list[Any] = []
    impacted_paths: list[Any] = []
    if wants_impact:
        impact = _safe_tool(
            toolbox, evidence, steps, state, "dependency_impact", service_id=subject_id
        )
        impacted = impact.data["impacted"] if impact else []
        impacted_paths = impact.data["paths"] if impact else []
    impacted_ids = [item.service.id for item in impacted]
    # The subject service is always in scope. Without this, an incident or
    # ownership question - where impact analysis may be skipped entirely -
    # would query an empty service list and find nothing.
    scope_ids = [subject_id, *impacted_ids]

    upstream = _safe_tool(
        toolbox, evidence, steps, state, "upstream_dependencies", service_id=subject_id
    )

    # Owners of the subject plus every impacted service, in one query.
    owners = _safe_tool(toolbox, evidence, steps, state, "owners_of", service_ids=scope_ids)

    engineers = (
        _safe_tool(
            toolbox, evidence, steps, state, "relevant_engineers", service_ids=scope_ids
        )
        if wants_ownership
        else None
    )
    incidents = (
        _safe_tool(
            toolbox, evidence, steps, state, "related_incidents", service_ids=scope_ids
        )
        if wants_incidents
        else None
    )
    decisions = (
        _safe_tool(
            toolbox, evidence, steps, state, "decision_history", service_ids=scope_ids
        )
        if wants_decisions
        else None
    )

    # Documents that explain the services and back the decisions.
    doc_entity_ids = [
        *scope_ids,
        *[d["id"] for d in (decisions.data if decisions else [])],
    ]
    documents = _safe_tool(
        toolbox, evidence, steps, state, "supporting_documents", entity_ids=doc_entity_ids
    )

    # -- Comparison-specific evidence --------------------------------------
    shared: list[dict[str, Any]] = []
    if comparison and comparison.id != subject_id:
        shared_result = _safe_tool(
            toolbox,
            evidence,
            steps,
            state,
            "shared_dependencies",
            service_a=subject_id,
            service_b=comparison.id,
        )
        shared = (shared_result.data if shared_result else []) or []
        _safe_tool(
            toolbox, evidence, steps, state, "upstream_dependencies", service_id=comparison.id
        )
        if wants_decisions:
            _safe_tool(
                toolbox, evidence, steps, state, "decision_history", service_ids=[comparison.id]
            )
        _safe_tool(
            toolbox, evidence, steps, state, "supporting_documents", entity_ids=[comparison.id]
        )
        _safe_tool(
            toolbox, evidence, steps, state, "owners_of", service_ids=[comparison.id]
        )

    updates.update(
        {
            "impacted": impacted,
            "paths": impacted_paths,
            "upstream": {
                subject_id: upstream.data if upstream else [],
                **( {comparison.id: []} if comparison else {} ),
            },
            "owners": owners.data if owners else {},
            "engineers": engineers.data if engineers else [],
            "incidents": incidents.data if incidents else [],
            "decisions": decisions.data if decisions else [],
            "documents": documents.data if documents else [],
            "shared_dependencies": shared,
            "evidence": evidence,
            "steps": steps,
            "tool_call_count": toolbox.calls_used,
        }
    )
    return updates


# --------------------------------------------------------------------------
# Node 3 - Evidence Assembler
# --------------------------------------------------------------------------


def _normalise_evidence(evidence: list[Evidence]) -> list[Evidence]:
    """Make an evidence bundle safe to cite and to key a list by.

    Both problems here only surface on comparison questions, where a tool runs
    once per side:

    * `entities` repeated a node whenever one person or service was reached by
      more than one route, so a single owner could be listed three times and
      the entity count overstated what was actually found. `source_ids` was
      already de-duplicated, so `entities` was the odd one out.
    * `evidence_id` was the tool's label rather than a unique id, so running
      `upstream_dependencies` for both services produced two records both
      called `ev-upstream`. Evidence is cited by id, which made that citation
      ambiguous, and it collided as a list key in the UI.

    The first record keeps its base label so the citations the recommendation
    builder writes still resolve; later repeats are suffixed.
    """
    used: dict[str, int] = {}
    normalised: list[Evidence] = []

    for item in evidence:
        seen: set[tuple[str, str]] = set()
        entities: list[NodeRef] = []
        for entity in item.entities:
            key = (str(entity.type), entity.id)
            if key in seen:
                continue
            seen.add(key)
            entities.append(entity)

        count = used.get(item.evidence_id, 0) + 1
        used[item.evidence_id] = count

        normalised.append(
            item.model_copy(
                update={
                    "entities": entities,
                    "evidence_id": item.evidence_id
                    if count == 1
                    else f"{item.evidence_id}#{count}",
                }
            )
        )

    return normalised


def assemble_evidence_node(state: InvestigationState) -> dict[str, Any]:
    """Normalise retrieved results into a single ordered evidence bundle.

    The writer sees a stable, compact view of what was found, including the
    explicit absences - those drive the "the graph does not record..." lines.
    """
    _phase(state, "assemble", "Assembling the evidence bundle")
    evidence = _normalise_evidence(list(state.get("evidence") or []))
    gaps: list[str] = []

    if not state.get("impacted"):
        gaps.append(
            "No downstream dependencies were recorded for the subject service."
        )
    if not state.get("decisions"):
        gaps.append("No architecture decisions were recorded for these services.")
    if not state.get("incidents"):
        gaps.append("No incidents are recorded against these services.")
    if not state.get("documents"):
        gaps.append("No documents are linked to these services.")

    owners = state.get("owners") or {}
    if owners:
        unowned = [sid for sid, people in owners.items() if not people]
        if unowned:
            gaps.append(f"No owner recorded for: {', '.join(sorted(unowned))}.")

    unknown_causes = [i["id"] for i in (state.get("incidents") or []) if not i.get("cause_names")]
    if unknown_causes:
        gaps.append(
            f"Incidents with no recorded cause: {', '.join(unknown_causes)}."
        )

    return {"evidence": evidence, "missing_evidence": gaps}


def render_evidence(state: InvestigationState) -> str:
    """Compact evidence view handed to the critic and writer."""
    lines: list[str] = []

    impacted = state.get("impacted") or []
    if impacted:
        lines.append("IMPACTED SERVICES (service - hops from change - criticality):")
        for item in impacted:
            lines.append(
                f"  [{item.service.id}] {item.service.name} - {item.depth} hop(s) - "
                f"criticality={item.criticality}"
            )

    owners = state.get("owners") or {}
    if owners:
        lines.append("OWNERS:")
        for service_id, people in owners.items():
            names = ", ".join(f"{p.name} [{p.id}] ({p.properties.get('role','')})" for p in people)
            lines.append(f"  {service_id}: {names or 'none recorded'}")

    engineers = state.get("engineers") or []
    if engineers:
        lines.append("ENGINEERS WITH HISTORY:")
        for row in engineers[:12]:
            lines.append(
                f"  [{row['person_id']}] {row['person_name']} ({row.get('person_role','')}) - "
                f"{row.get('reason','project')} on {row.get('project_name','')} [{row.get('service_id','')}]"
            )

    incidents = state.get("incidents") or []
    if incidents:
        lines.append("INCIDENTS:")
        for row in incidents[:12]:
            cause = ", ".join(row.get("cause_names") or []) or "CAUSE NOT RECORDED"
            lines.append(
                f"  [{row['id']}] {row.get('severity','')} {row.get('title','')} "
                f"({row.get('occurred_at','')}) affected {row.get('service_name','')} - cause: {cause}"
            )

    decisions = state.get("decisions") or []
    if decisions:
        lines.append("DECISIONS:")
        for row in decisions[:12]:
            superseded = ", ".join(t for t in (row.get("superseded_by_titles") or []) if t)
            lines.append(
                f"  [{row['id']}] {row.get('status','')} {row.get('date','')}: {row.get('title','')}"
            )
            if row.get("rationale"):
                lines.append(f"      rationale: {row['rationale'][:400]}")
            if superseded:
                lines.append(f"      SUPERSEDED BY: {superseded}")

    documents = state.get("documents") or []
    if documents:
        lines.append("DOCUMENTS:")
        for row in documents[:10]:
            lines.append(
                f"  [{row['id']}] ({row.get('source_type','')}) {row.get('title','')} - "
                f"{row.get('relation_type','')} {row.get('entity_id','')}"
            )
            if row.get("content"):
                lines.append(f"      {row['content'][:500]}")

    shared = state.get("shared_dependencies") or []
    if shared:
        names = ", ".join(f"{s.get('name')} [{s.get('id')}]" for s in shared)
        lines.append(f"SHARED DEPENDENCIES: {names}")

    upstream = state.get("upstream") or {}
    for service_id, rows in upstream.items():
        if rows:
            names = ", ".join(f"{r.get('name')} [{r.get('id')}]" for r in rows)
            lines.append(f"{service_id} DEPENDS ON: {names}")

    recalled = state.get("recalled") or []
    if recalled:
        lines.append("PREVIOUS INVESTIGATIONS:")
        for row in recalled[:3]:
            lines.append(f"  [{row['id']}] {row.get('question','')}")

    gaps = state.get("missing_evidence") or []
    if gaps:
        lines.append("KNOWN GAPS IN EVIDENCE:")
        for gap in gaps:
            lines.append(f"  - {gap}")

    return "\n".join(lines) if lines else "(no evidence retrieved)"


# --------------------------------------------------------------------------
# Node 4 - Critic
# --------------------------------------------------------------------------


def _known_ids(state: InvestigationState) -> set[str]:
    """Every entity id this investigation legitimately retrieved.

    This is the critic's whitelist, so it must be complete: an id missing here
    produces a false "unsupported claim" on a perfectly grounded answer, and a
    critic that cries wolf is worse than no critic.

    The first draft only read evidence `source_ids`, which quietly omitted the
    subject service (impact traversal returns *downstream* services, never the
    one being asked about) and the project ids behind engineer history. Both are
    legitimately citable.
    """
    ids: set[str] = set()

    for record in state.get("evidence") or []:
        ids.update(record.source_ids)
        ids.update(node.id for node in record.entities)

    # The premise of the question is itself grounded.
    for key in ("resolved_subject", "resolved_comparison"):
        node = state.get(key)
        if node is not None:
            ids.add(node.id)

    for item in state.get("impacted") or []:
        ids.add(item.service.id)
        ids.update(owner.id for owner in item.owners)

    for row in state.get("engineers") or []:
        ids.update(
            {row.get("person_id", ""), row.get("project_id", ""), row.get("service_id", "")}
        )

    for row in state.get("incidents") or []:
        ids.add(row.get("id", ""))
        ids.update(row.get("cause_ids") or [])
        ids.update(row.get("resolver_ids") or [])

    for row in state.get("decisions") or []:
        ids.add(row.get("id", ""))
        ids.update(row.get("superseded_by_ids") or [])

    for row in state.get("documents") or []:
        ids.update({row.get("id", ""), row.get("entity_id", "")})

    for row in state.get("shared_dependencies") or []:
        ids.add(row.get("id", ""))

    for rows in (state.get("upstream") or {}).values():
        for row in rows:
            ids.add(row.get("id", ""))

    for row in state.get("recalled") or []:
        ids.add(row.get("id", ""))

    return {i for i in ids if i}


def critic_node(state: InvestigationState) -> dict[str, Any]:
    """Check the draft against the evidence before it is shown to anyone.

    Runs a deterministic citation audit first - every `[id]` in the draft must
    correspond to a retrieved entity - and then asks the model to reason about
    semantics the regex cannot see.
    """
    _phase(state, "critic", "Checking claims against the evidence")
    steps: list[ExecutionStep] = []
    known = _known_ids(state)

    draft = state.get("answer") or ""
    cited = set(_CITATION_RE.findall(draft))
    unsupported = sorted(
        citation
        for citation in cited
        # A real entity id looks like `svc-x`; anything else is prose in brackets.
        if citation not in known and "-" in citation
    )

    critique = Critique(
        verdict="qualify" if unsupported else "pass",
        unsupported_claims=[
            f"Answer cites [{cid}], which no retrieved evidence record supports."
            for cid in unsupported
        ],
        missing_evidence=list(state.get("missing_evidence") or []),
    )

    rendered = render_evidence(state)
    raw = _invoke(
        CRITIC_SYSTEM,
        CRITIC_USER.format(answer=draft[:6000], evidence=rendered[:12000]),
        timeout=get_settings().agent_query_timeout_seconds,
    )
    parsed = _extract_json(raw) if raw else None
    if parsed:
        model_unsupported = [
            str(c) for c in (parsed.get("unsupported_claims") or []) if str(c).strip()
        ]
        # Union the deterministic and model findings; never let the model drop one.
        critique.unsupported_claims = list(
            dict.fromkeys([*critique.unsupported_claims, *model_unsupported])
        )
        critique.contradictions = [
            str(c) for c in (parsed.get("contradictions") or []) if str(c).strip()
        ]
        critique.missing_evidence = list(
            dict.fromkeys(
                [
                    *critique.missing_evidence,
                    *[str(c) for c in (parsed.get("missing_evidence") or []) if str(c).strip()],
                ]
            )
        )
        critique.notes = str(parsed.get("notes") or "")
        if critique.unsupported_claims or critique.contradictions:
            critique.verdict = "qualify"

    steps.append(
        ExecutionStep(
            node="critic",
            title="Verify claims against evidence",
            status="completed",
            detail=(
                f"{len(cited)} citation(s) checked, {len(unsupported)} ungrounded, "
                f"{len(critique.contradictions)} contradiction(s)"
            ),
            tool="critic",
        )
    )

    return {"critique": critique.model_dump(), "steps": steps}


# --------------------------------------------------------------------------
# Node 5 - Writer
# --------------------------------------------------------------------------


def dedupe_people(people: list[NodeRef]) -> list[NodeRef]:
    """De-duplicate people by id, preserving first-seen order.

    Pydantic models are unhashable, so `dict.fromkeys` cannot be used here.
    """
    seen: set[str] = set()
    unique: list[NodeRef] = []
    for person in people:
        if person.id in seen:
            continue
        seen.add(person.id)
        unique.append(person)
    return unique


def build_recommendations(state: InvestigationState) -> list[Recommendation]:
    """Derive next steps from graph structure only.

    Every recommendation is anchored to evidence: reviewers come from ownership
    edges, and the migration checklist comes from the documented gaps.
    """
    recommendations: list[Recommendation] = []
    owners = state.get("owners") or {}
    impacted = state.get("impacted") or []

    critical = [i for i in impacted if i.criticality == "critical"]

    if critical:
        reviewer_ids = [i.service.id for i in critical]
        reviewer_people: list[NodeRef] = []
        for sid in reviewer_ids:
            reviewer_people.extend(owners.get(sid, []))
        recommendations.append(
            Recommendation(
                action=(
                    "Get sign-off from the owners of every critical impacted service "
                    "before any cutover."
                ),
                rationale=(
                    f"{len(critical)} critical service(s) depend on the service being "
                    "replaced within the configured traversal depth."
                ),
                evidence_ids=["ev-impact", "ev-owners"],
                suggested_reviewers=dedupe_people(reviewer_people)[:8],
            )
        )

    # Engineers with the most recorded engagements are the natural reviewers.
    engineers = state.get("engineers") or []
    if engineers:
        seen: set[str] = set()
        candidates: list[NodeRef] = []
        for row in engineers:
            pid = row.get("person_id", "")
            if pid in seen:
                continue
            seen.add(pid)
            candidates.append(
                NodeRef(
                    id=pid,
                    type="Person",
                    name=row.get("person_name", ""),
                    properties={
                        "role": row.get("person_role", ""),
                        "team": row.get("person_team", ""),
                    },
                )
            )
        recommendations.append(
            Recommendation(
                action=(
                    "Route the change review to engineers with recorded project or "
                    "incident history on the impacted services."
                ),
                rationale=(
                    f"{len(candidates)} people have recorded engagement with the "
                    "impacted services."
                ),
                evidence_ids=["ev-engineers"],
                suggested_reviewers=candidates[:8],
            )
        )

    incidents = state.get("incidents") or []
    sev1 = [i for i in incidents if i.get("severity") in ("sev1", "sev2")]
    if sev1:
        recommendations.append(
            Recommendation(
                action=(
                    "Review the recorded postmortems for the most severe incidents on "
                    "this path before planning the migration."
                ),
                rationale=(
                    f"{len(sev1)} sev1/sev2 incident(s) are recorded against these "
                    "services; each is a concrete failure mode to test against."
                ),
                evidence_ids=["ev-incidents"],
            )
        )

    unknown_causes = [i["id"] for i in incidents if not i.get("cause_names")]
    if unknown_causes:
        recommendations.append(
            Recommendation(
                action=(
                    "Investigate the unresolved incidents before assuming the migration "
                    "addresses their root cause."
                ),
                rationale=(
                    f"{len(unknown_causes)} incident(s) have no recorded cause, so their "
                    "risk contribution cannot be assessed from the graph."
                ),
                evidence_ids=["ev-incidents"],
            )
        )

    shared = state.get("shared_dependencies") or []
    if shared:
        recommendations.append(
            Recommendation(
                action=(
                    "Verify that every shared dependency supports both services "
                    "simultaneously during the migration window."
                ),
                rationale=(
                    f"{len(shared)} service(s) are dependencies of both the old and the "
                    "replacement service: "
                    + ", ".join(s.get("name", "") for s in shared)
                ),
                evidence_ids=["ev-shared"],
            )
        )

    return recommendations


def _deterministic_answer(state: InvestigationState) -> str:
    """Compose a grounded answer with no model in the loop.

    Used when the LLM is unavailable and as the safety net that guarantees the
    API always returns something evidence-backed rather than an error page.
    """
    subject = state.get("resolved_subject")
    comparison = state.get("resolved_comparison")
    impacted = state.get("impacted") or []
    decisions = state.get("decisions") or []
    incidents = state.get("incidents") or []
    owners = state.get("owners") or {}

    subject_label = subject.name if subject else "the service in question"
    sections: list[str] = []

    # Verdict
    critical = [i for i in impacted if i.criticality == "critical"]
    if comparison:
        verdict = (
            f"Replacing {subject_label} [{subject.id}] with {comparison.name} "
            f"[{comparison.id}] is **not a contained change**. "
            f"{len(impacted)} service(s) sit downstream of it, including "
            f"{len(critical)} marked critical. The graph does not yet record a "
            "completed migration, so this should be treated as a planned change "
            "requiring staged cutover."
        )
    else:
        verdict = (
            f"{len(impacted)} service(s) depend on {subject_label} "
            f"[{subject.id if subject else 'unknown'}] within the configured traversal depth."
        )
    sections.append(f"## Verdict\n\n{verdict}\n")

    if impacted:
        lines = ["## What depends on it\n"]
        for item in impacted:
            owner_names = (
                ", ".join(p.name for p in owners.get(item.service.id, []))
                or "no owner recorded"
            )
            lines.append(
                f"- **{item.service.name}** `{item.service.id}` - {item.depth} hop(s), "
                f"criticality **{item.criticality}** - owner: {owner_names}"
            )
        sections.append("\n".join(lines) + "\n")

    if decisions:
        lines = ["## Why the current service is used\n"]
        for row in decisions[:6]:
            lines.append(f"### {row.get('title')} `{row.get('id')}`")
            lines.append(
                f"*Status {row.get('status')} on {row.get('date')}.* "
                f"{row.get('rationale','')}"
            )
            superseded = [t for t in (row.get("superseded_by_titles") or []) if t]
            if superseded:
                lines.append(f"**Superseded by:** {', '.join(superseded)}")
            lines.append("")
        sections.append("\n".join(lines))

    engineers = state.get("engineers") or []
    if owners or engineers:
        lines = ["## Who should review this\n"]
        for service_id, people in list(owners.items())[:8]:
            for person in people:
                lines.append(
                    f"- **{person.name}** `{person.id}` - owns `{service_id}` "
                    f"({person.properties.get('role','')})"
                )
        for row in engineers[:6]:
            lines.append(
                f"- **{row.get('person_name')}** `{row.get('person_id')}` - "
                f"{row.get('reason')} on {row.get('project_name')} "
                f"[{row.get('project_id')}]"
            )
        sections.append("\n".join(lines) + "\n")

    # Risks and unknowns
    lines = ["## Risks and unknowns\n"]
    shared = state.get("shared_dependencies") or []
    if shared:
        lines.append(
            "**Potential risk.** Both services share these dependencies, which must "
            "support the old and new paths at once: "
            + ", ".join(f"{s.get('name')} `{s.get('id')}`" for s in shared)
            + "."
        )
    for gap in state.get("missing_evidence") or []:
        lines.append(f"- **Unknown.** {gap}")
    for incident in incidents:
        if not incident.get("cause_names"):
            lines.append(
                f"- **Unknown cause.** Incident `{incident.get('id')}` "
                f"({incident.get('severity')}) has no CAUSED_BY relationship in the graph. "
                "The agent cannot determine why it happened."
            )
    if not shared and not state.get("missing_evidence"):
        lines.append("- No additional gaps were detected in the retrieved evidence.")
    sections.append("\n".join(lines) + "\n")

    recommendations = build_recommendations(state)
    if recommendations:
        lines = ["## Recommended next steps\n"]
        for idx, rec in enumerate(recommendations, start=1):
            lines.append(f"{idx}. {rec.action}")
            lines.append(f"   {rec.rationale}")
            if rec.suggested_reviewers:
                names = ", ".join(
                    f"{p.name} `{p.id}`" for p in rec.suggested_reviewers[:5]
                )
                lines.append(f"   Suggested reviewers: {names}")
        sections.append("\n".join(lines) + "\n")

    return "\n".join(sections).strip()


def write_node(state: InvestigationState) -> dict[str, Any]:
    """Generate the final answer, then run the deterministic citation audit."""
    _phase(state, "write", "Drafting the answer")
    steps: list[ExecutionStep] = []
    rendered = render_evidence(state)
    caveats = list(state.get("missing_evidence") or [])

    raw = _invoke(
        WRITER_SYSTEM,
        WRITER_USER.format(
            question=state["question"],
            evidence=rendered[:14000],
            paths=_render_paths(state),
            caveats="\n".join(f"- {c}" for c in caveats) or "- none",
        ),
        timeout=get_settings().agent_query_timeout_seconds,
    )

    if raw.strip():
        answer = raw.strip()
        source = "NVIDIA NIM"
        detail = "Answer written by the model and grounded in retrieved evidence"
    else:
        answer = _deterministic_answer(state)
        source = "deterministic fallback"
        detail = "Model unavailable - answer composed directly from graph evidence"

    steps.append(
        ExecutionStep(
            node="write",
            title="Compose grounded answer",
            status="completed",
            detail=detail,
            tool=source,
        )
    )

    # Confirmed if every id the answer cites actually came back from the graph.
    known = _known_ids(state)
    cited = set(_CITATION_RE.findall(answer))
    grounded = cited & known
    confidence = "high" if cited and not (cited - known) else "moderate"
    if not cited:
        confidence = "low"

    return {
        "answer": answer,
        "confidence": confidence,
        "steps": steps,
        "cited_ids": sorted(grounded),
        "recommendations": build_recommendations(state),
    }


def _render_paths(state: InvestigationState) -> str:
    """Human-readable dependency paths for the writer."""
    paths = state.get("paths") or []
    if not paths:
        return "(no dependency paths retrieved)"
    return "\n".join(f"- {path.describe()}" for path in paths[:20])


# --------------------------------------------------------------------------
# Node 6 - Memory
# --------------------------------------------------------------------------


def memory_node(state: InvestigationState) -> dict[str, Any]:
    """Persist the investigation and its citations into the graph."""
    _phase(state, "memory", "Saving what was learned")
    steps: list[ExecutionStep] = []
    toolbox: GraphToolbox = state["_toolbox"]  # type: ignore[index]

    cited = list(state.get("cited_ids") or [])
    if not cited:
        cited = sorted(_known_ids(state))[:40]

    try:
        toolbox.repository.save_investigation(
            investigation_id=state["investigation_id"],
            question=state["question"],
            answer=state.get("answer", ""),
            summary=_summarise(state),
            status="completed",
            cited_ids=cited,
            metadata={
                "intent": (state.get("plan") or {}).get("intent"),
                "confidence": state.get("confidence"),
                "tool_calls": toolbox.calls_used,
                "critic_verdict": (state.get("critique") or {}).get("verdict"),
            },
        )
        steps.append(
            ExecutionStep(
                node="memory",
                title="Persist investigation for future sessions",
                status="completed",
                detail=f"{len(cited)} citation(s) linked",
                tool="save_investigation",
            )
        )
    except Exception as exc:  # noqa: BLE001 - memory failure must not lose the answer
        logger.error("Failed to persist investigation: %s", exc)
        steps.append(
            ExecutionStep(
                node="memory",
                title="Persist investigation",
                status="failed",
                detail=str(exc),
                tool="save_investigation",
            )
        )

    return {
        "status": "completed",
        "steps": steps,
        "cited_ids": cited,
        "investigation_id": state["investigation_id"],
    }


def _summarise(state: InvestigationState) -> str:
    """One-paragraph summary stored alongside the full answer."""
    impacted = state.get("impacted") or []
    plan = InvestigationPlan(**state["plan"])  # type: ignore[arg-type]
    subject = state.get("resolved_subject")
    bits = [f"Question: {state['question']}"]
    if subject:
        bits.append(f"Subject: {subject.name} ({subject.id}).")
    bits.append(f"Intent: {plan.intent}.")
    bits.append(f"{len(impacted)} impacted service(s), ")
    bits.append(f"{len(state.get('incidents') or [])} incident(s), ")
    bits.append(f"{len(state.get('decisions') or [])} decision(s) retrieved.")
    if state.get("confidence"):
        bits.append(f"Confidence: {state['confidence']}.")
    return " ".join(bits)


def new_investigation_id() -> str:
    """Collision-resistant, sortable investigation identifier."""
    return f"inv-{uuid.uuid4().hex[:12]}"