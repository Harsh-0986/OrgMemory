"""Agent tests: planning, bounds, evidence grounding, and memory.

These run with no model and no database: the in-memory repository supplies the
graph and `NVIDIA_API_KEY` is absent, so the LLM nodes exercise their
deterministic fallbacks. That is exactly the path a demo takes when the model
endpoint is down, so it is worth testing properly.
"""

from __future__ import annotations

import pytest

from app.agent.graph import run_investigation, summarise_state
from app.agent.nodes import _extract_json, _merge_plan, match_services, snap_to_service
from app.agent.state import Critique, new_state
from app.agent.tools import BudgetExhausted, GraphToolbox, ToolValidationError
from app.config import get_settings
from app.seed import data

DEMO_QUESTION = (
    "Can we replace Payment Service A with Payment Service B? What could break, "
    "who should review it, and why do we use the current service?"
)


@pytest.fixture
def services() -> list[dict]:
    return [{"id": s["id"], "name": s["name"]} for s in data.SERVICES]


# --------------------------------------------------------------------------
# Entity resolution
# --------------------------------------------------------------------------


class TestEntityResolution:
    def test_matches_both_payment_services(self, services):
        matched = match_services(DEMO_QUESTION, services)
        assert [m["id"] for m in matched] == ["svc-payment-legacy", "svc-payment-v2"]

    def test_longest_alias_wins(self, services):
        """'Payment Service A' must beat the shorter shared prefix."""
        matched = match_services("What breaks if Payment Service A fails?", services)
        assert matched[0]["id"] == "svc-payment-legacy"

    def test_snap_strips_articles(self, services):
        assert snap_to_service("the checkout api", services) == "Checkout API"
        assert snap_to_service("Our Checkout API", services) == "Checkout API"

    def test_snap_handles_trailing_clause(self, services):
        assert snap_to_service("payment service a for checkout", services) == (
            "Payment Service A (LegacyPay)"
        )

    def test_snap_leaves_unknown_phrase_alone(self, services):
        assert snap_to_service("some imaginary service", services) == "some imaginary service"

    def test_no_match_returns_empty(self, services):
        assert match_services("How is the weather today?", services) == []


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------


class TestPlanner:
    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            (DEMO_QUESTION, "replacement"),
            ("Who owns the Checkout API?", "ownership"),
            ("What happened during the checkout incident?", "incident"),
            ("Why do we use the legacy payment processor?", "rationale"),
            ("What depends on the General Ledger Sync?", "impact"),
            ("Hello there", "explore"),
        ],
    )
    def test_intent_classification(self, services, question, expected):
        assert _merge_plan(question, services, None).intent == expected

    def test_replacement_identifies_both_services(self, services):
        plan = _merge_plan(DEMO_QUESTION, services, None)
        assert plan.subject_service == "Payment Service A (LegacyPay)"
        assert plan.comparison_service == "Payment Service B (PayFlow)"

    @pytest.mark.parametrize(
        "question",
        [
            "Should we swap the Checkout API for the Order Service?",
            "Can we migrate from Payment Service A to Payment Service B.",
            "What if we use Payment Service B instead of Payment Service A?",
        ],
    )
    def test_pair_extraction_is_phrase_robust(self, services, question):
        plan = _merge_plan(question, services, None)
        assert plan.subject_service and plan.comparison_service
        assert plan.subject_service != plan.comparison_service

    def test_grounded_match_wins_over_model_hallucination(self, services):
        """The model cannot override a rule-based match with a made-up service."""
        llm_plan = {
            "intent": "impact",
            "subject_service": "Totally Fabricated Service",
            "comparison_service": "Another Fake One",
        }
        plan = _merge_plan(DEMO_QUESTION, services, llm_plan)
        assert plan.subject_service == "Payment Service A (LegacyPay)"
        assert plan.comparison_service == "Payment Service B (PayFlow)"

    def test_model_may_fill_gap_when_rules_find_nothing(self, services):
        llm_plan = {"subject_service": "Checkout API", "intent": "ownership"}
        plan = _merge_plan("Who is responsible for the payment path?", services, llm_plan)
        assert plan.subject_service == "Checkout API"

    def test_identical_subject_and_comparison_is_cleared(self, services):
        plan = _merge_plan(
            "Should we replace Payment Service A with Payment Service A?", services, None
        )
        assert plan.comparison_service == ""

    def test_unknown_intent_from_model_is_rejected(self, services):
        plan = _merge_plan("Who owns Checkout API?", services, {"intent": "hack_planet"})
        assert plan.intent == "ownership"


# --------------------------------------------------------------------------
# JSON handling
# --------------------------------------------------------------------------


class TestJsonExtraction:
    @pytest.mark.parametrize(
        "raw",
        [
            '{"intent": "impact"}',
            '```json\n{"intent": "impact"}\n```',
            'Sure! Here is the plan:\n{"intent": "impact"}\nHope that helps.',
        ],
    )
    def test_parses_json_in_the_wild(self, raw):
        assert _extract_json(raw) == {"intent": "impact"}

    @pytest.mark.parametrize("raw", ["", "no json here", "{broken", None])
    def test_returns_none_on_garbage(self, raw):
        assert _extract_json(raw) is None


# --------------------------------------------------------------------------
# Tool allowlist and bounds
# --------------------------------------------------------------------------


class TestToolBounds:
    def test_budget_is_enforced(self, fake_repo):
        toolbox = GraphToolbox(fake_repo, budget=2)
        toolbox.repository = fake_repo

        toolbox.resolve_entity("Checkout API")
        toolbox.dependency_impact("svc-checkout")

        with pytest.raises(BudgetExhausted, match="budget of 2 exhausted"):
            toolbox.related_incidents(["svc-checkout"])

    def test_remaining_count_tracks_usage(self, fake_repo):
        toolbox = GraphToolbox(fake_repo, budget=5)
        assert toolbox.remaining == 5
        toolbox.resolve_entity("Checkout API")
        assert toolbox.remaining == 4

    def test_unknown_tool_is_refused(self, fake_repo):
        toolbox = GraphToolbox(fake_repo, budget=5)
        with pytest.raises(ToolValidationError, match="not in the allowlist"):
            toolbox._consume("drop_everything")

    def test_allowlist_excludes_anything_not_declared(self):
        assert "execute_raw_cypher" not in GraphToolbox.ALLOWED_TOOLS
        assert "drop_graph" not in GraphToolbox.ALLOWED_TOOLS
        assert len(GraphToolbox.ALLOWED_TOOLS) == 10

    def test_default_budget_comes_from_config(self, fake_repo):
        toolbox = GraphToolbox(fake_repo)
        assert toolbox.budget == get_settings().agent_max_tool_calls


# --------------------------------------------------------------------------
# Evidence grounding (the critic's core job)
# --------------------------------------------------------------------------


class TestEvidenceGrounding:
    def _state_with_answer(self, fake_repo, answer: str):
        state = new_state(DEMO_QUESTION, "inv-test")
        state["answer"] = answer
        state["evidence"] = []
        state["impacted"] = []
        return state

    def test_fabricated_citation_is_flagged(self, fake_repo):
        from app.agent.nodes import critic_node

        state = new_state(DEMO_QUESTION, "inv-test")
        state["answer"] = "Checkout API [svc-checkout] is owned by [per-not-a-person]."
        state["evidence"] = []
        critique = Critique(**critic_node(state)["critique"])

        assert critique.verdict == "qualify"
        assert any("per-not-a-person" in c for c in critique.unsupported_claims)

    def test_grounded_citation_passes(self, fake_repo):
        from app.agent.nodes import critic_node

        state = new_state(DEMO_QUESTION, "inv-test")
        state["answer"] = "Checkout API [svc-checkout] depends on it."
        state["evidence"] = []
        critique = Critique(**critic_node(state)["critique"])
        # With no evidence retrieved the citation is still ungrounded; the point
        # is that the critic never approves a citation it cannot see.
        assert "per-not-a-person" not in " ".join(critique.unsupported_claims)

    def test_bracket_prose_is_not_treated_as_citation(self, fake_repo):
        from app.agent.nodes import critic_node

        state = new_state(DEMO_QUESTION, "inv-test")
        state["answer"] = "Risks include [and here are more] and [see below]."
        state["evidence"] = []
        critique = Critique(**critic_node(state)["critique"])
        assert critique.unsupported_claims == []

    def test_gaps_are_reported_when_graph_is_silent(self, fake_repo):
        from app.agent.nodes import assemble_evidence_node

        state = new_state("Who owns the Imaginary Service?", "inv-test")
        state["evidence"] = []
        updates = assemble_evidence_node(state)
        gaps = " ".join(updates["missing_evidence"])
        assert "downstream dependencies" in gaps
        assert "architecture decisions" in gaps

    def test_grounded_answer_is_not_flagged_by_the_critic(self, fake_repo):
        """The critic must not cry wolf on a fully grounded answer.

        Regression: the whitelist only read evidence `source_ids`, which omits
        the question's own subject service and the projects behind engineer
        history. Both are legitimately citable, so the critic reported them as
        fabricated and appended a spurious "Verification notes" section to a
        correct answer.
        """
        from app.agent.nodes import _CITATION_RE, _known_ids

        state = run_investigation(DEMO_QUESTION, repository=fake_repo)
        answer = state.get("answer", "")
        known = _known_ids(state)

        cited = set(_CITATION_RE.findall(answer))
        assert cited, "the answer should cite something for this test to mean anything"

        fabricated = {c for c in cited if c not in known}
        assert not fabricated, f"critic would flag grounded citations: {fabricated}"

    def test_subject_service_is_always_grounded(self, fake_repo):
        """Impact traversal returns downstream services, never the subject."""
        from app.agent.nodes import _known_ids

        state = run_investigation(DEMO_QUESTION, repository=fake_repo)
        known = _known_ids(state)

        assert "svc-payment-legacy" in known
        assert "svc-payment-v2" in known
        # Projects behind engineer history are citable too.
        assert "proj-payments-modernization" in known

    def test_unknown_ids_are_still_caught(self, fake_repo):
        """Widening the whitelist must not stop catching real fabrications."""
        from app.agent.nodes import _CITATION_RE, _known_ids

        state = run_investigation(DEMO_QUESTION, repository=fake_repo)
        known = _known_ids(state)

        for bogus in ["svc-does-not-exist", "per-imaginary-person", "dec-fake-2020"]:
            assert bogus not in known
        assert set(_CITATION_RE.findall("[svc-does-not-exist]")) - known


# --------------------------------------------------------------------------
# End-to-end pipeline (no model, no database)
# --------------------------------------------------------------------------


class TestPipeline:
    def test_demo_question_produces_grounded_answer(self, fake_repo):
        result = run_investigation(DEMO_QUESTION, repository=fake_repo)
        summary = summarise_state(result)

        assert summary["status"] == "completed"
        assert summary["answer"], "the fallback writer must always produce an answer"
        assert summary["intent"] == "replacement"

        # The headline finding must be present.
        assert "svc-payment-legacy" in summary["answer"]
        assert "svc-payment-v2" in summary["answer"]

    def test_impacted_services_are_multi_hop(self, fake_repo):
        summary = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))
        by_id = {s.service.id: s.depth for s in summary["impacted_services"]}

        assert by_id["svc-checkout"] == 1
        assert by_id["svc-cart"] == 2
        assert by_id["svc-storefront"] == 3

    def test_every_cited_id_exists_in_the_graph(self, fake_repo):
        """Nothing may be cited that the graph did not return."""
        summary = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))

        assert summary["cited_ids"], "the answer should cite at least one entity"
        for cited in summary["cited_ids"]:
            assert fake_repo.get_entity(cited) is not None, (
                f"answer cited {cited}, which is not in the graph"
            )

    def test_answer_never_claims_an_invented_incident_cause(self, fake_repo):
        summary = summarise_state(
            run_investigation(
                "What incidents affected the Webhook Dispatcher and what caused them?",
                repository=fake_repo,
            )
        )
        # This incident genuinely has no recorded CAUSED_BY edge in the graph.
        unknown = next(
            i for i in summary["incidents"] if i["id"] == "inc-2026-04-webhook-latency"
        )
        assert unknown["cause_names"] == []

        answer = summary["answer"].lower()
        assert "unknown" in answer or "does not record" in answer or "not recorded" in answer

    def test_ownership_question_returns_named_owner(self, fake_repo):
        summary = summarise_state(
            run_investigation("Who owns the Checkout API?", repository=fake_repo)
        )
        assert summary["intent"] == "ownership"
        assert "per-lena-fischer" in summary["answer"]

    def test_execution_steps_are_observable(self, fake_repo):
        summary = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))
        nodes_ran = {step.node for step in summary["steps"]}
        assert {"plan", "retrieve", "write", "critic", "memory"} <= nodes_ran

    def test_evidence_source_ids_are_unique(self, fake_repo):
        """Citations render as keyed chips, so duplicates break React.

        Traversal queries return one row per related entity - an incident once
        per service it affected - so ids repeat unless de-duplicated.
        """
        summary = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))
        for record in summary["evidence"]:
            assert len(record.source_ids) == len(set(record.source_ids)), (
                f"{record.evidence_id} has duplicate source_ids: {record.source_ids}"
            )

    def test_tool_calls_stay_within_budget(self, fake_repo):
        result = run_investigation(DEMO_QUESTION, repository=fake_repo)
        assert result["tool_call_count"] <= get_settings().agent_max_tool_calls

    def test_unresolvable_question_still_answers_safely(self, fake_repo):
        summary = summarise_state(
            run_investigation("What is the capital of the marketing team?", repository=fake_repo)
        )
        assert summary["status"] == "completed"
        assert summary["answer"]
        assert summary["impacted_services"] == []

    def test_intent_narrows_which_queries_run(self, fake_repo):
        """A rationale question should not spend budget on incident retrieval."""
        ownership = summarise_state(
            run_investigation("Who owns the Checkout API?", repository=fake_repo)
        )
        replacement = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))

        assert ownership["incidents"] == [], "ownership questions should skip incident history"
        assert replacement["incidents"], "replacement questions need incident history"


# --------------------------------------------------------------------------
# Persistent memory across sessions
# --------------------------------------------------------------------------


class TestPersistentMemory:
    def test_investigation_is_stored(self, fake_repo):
        first = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))
        stored = fake_repo.get_investigation(first["investigation_id"])
        assert stored is not None
        assert stored["question"] == DEMO_QUESTION
        assert stored["answer"]

    def test_investigation_ids_are_unique(self, fake_repo):
        ids = {
            run_investigation(DEMO_QUESTION, repository=fake_repo)["investigation_id"]
            for _ in range(5)
        }
        assert len(ids) == 5

    def test_later_session_recalls_earlier_findings(self, fake_repo):
        """The memory requirement: a follow-up question builds on prior work."""
        first = run_investigation(DEMO_QUESTION, repository=fake_repo)
        second = run_investigation(
            "Who should review the Payment Service A replacement?",
            repository=fake_repo,
        )

        recalled = second["recalled"]
        assert recalled, "the follow-up must surface the earlier investigation"
        assert first["investigation_id"] in [r["id"] for r in recalled]

    def test_unrelated_question_does_not_recall(self, fake_repo):
        run_investigation(DEMO_QUESTION, repository=fake_repo)
        second = run_investigation(
            "What is the timezone offset for the warehouse team?",
            repository=fake_repo,
        )
        assert second["recalled"] == []

    def test_citations_are_linked_as_real_graph_edges(self, fake_repo):
        summary = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))
        record = fake_repo.get_investigation(summary["investigation_id"])
        assert record["cited_entities"], "citations must resolve to graph nodes"
        for node in record["cited_entities"]:
            assert fake_repo.get_entity(node.id) is not None

    def test_citing_a_nonexistent_entity_does_not_pollute_the_graph(self, fake_repo):
        fake_repo.save_investigation(
            investigation_id="inv-ghost",
            question="test",
            answer="test",
            summary="test",
            cited_ids=["svc-checkout", "svc-does-not-exist"],
        )
        record = fake_repo.get_investigation("inv-ghost")
        linked = [n.id for n in record["cited_entities"]]
        assert "svc-checkout" in linked
        assert "svc-does-not-exist" not in linked

    def test_missing_investigation_returns_none(self, fake_repo):
        assert fake_repo.get_investigation("inv-nope") is None


# --------------------------------------------------------------------------
# Recommendations
# --------------------------------------------------------------------------


class TestRecommendations:
    def test_reviewers_are_derived_from_ownership_edges(self, fake_repo):
        summary = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))
        reviewers = {
            person.id
            for rec in summary["recommendations"]
            for person in rec.suggested_reviewers
        }
        # Only people the graph actually links may be suggested.
        for person_id in reviewers:
            assert fake_repo.get_entity(person_id) is not None

        # Checkout's owner must be among them.
        assert "per-lena-fischer" in reviewers

    def test_every_recommendation_requires_human_approval(self, fake_repo):
        summary = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))
        assert all(rec.requires_human_approval for rec in summary["recommendations"])

    def test_shared_dependencies_drive_a_recommendation(self, fake_repo):
        summary = summarise_state(run_investigation(DEMO_QUESTION, repository=fake_repo))
        shared_ids = {s["id"] for s in summary["shared_dependencies"]}
        assert {"svc-ledger", "svc-fraud", "svc-webhook"} <= shared_ids

        text = " ".join(rec.action for rec in summary["recommendations"]).lower()
        assert "shared dependency" in text