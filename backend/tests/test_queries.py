"""Graph query layer tests.

These run against the in-memory repository by default so the expected answers
are pinned in CI. Tests marked `integration` run the same assertions against a
live FalkorDB instance to prove the Cypher agrees with the reference model.
"""

from __future__ import annotations

import pytest

from app.graph import queries
from app.seed import data, validate_dataset

# --------------------------------------------------------------------------
# Dataset integrity
# --------------------------------------------------------------------------


def test_dataset_is_internally_consistent():
    """Every relationship must point at entities that exist."""
    validate_dataset()


def test_dataset_has_no_duplicate_ids():
    ids = data.all_node_ids()
    total = sum(
        len(c) for c in (data.PEOPLE, data.SERVICES, data.PROJECTS,
                         data.INCIDENTS, data.DECISIONS, data.DOCUMENTS)
    )
    assert len(ids) == total, "duplicate entity ids in the seed dataset"


def test_dangling_relationships_are_detected():
    """The validator must actually reject bad data, not just pass good data."""
    from app.seed.seed import SeedValidationError, validate_dataset

    original = data.DEPENDENCIES.copy()
    data.DEPENDENCIES.append(("svc-does-not-exist", "DEPENDS_ON", "svc-checkout"))
    try:
        with pytest.raises(SeedValidationError, match="unknown entities"):
            validate_dataset()
    finally:
        data.DEPENDENCIES[:] = original


def test_dependency_direction_is_consistent():
    """A consumer must never also be recorded as a dependency of its provider."""
    deps = {(a, b) for a, rel, b in data.DEPENDENCIES if rel == "DEPENDS_ON"}
    for consumer, provider in deps:
        assert (provider, consumer) not in deps, (
            f"{consumer} -> {provider} and the reverse are both recorded; "
            "impact analysis would be ambiguous"
        )


def test_unknown_cause_incident_has_no_caused_by_edge():
    """The dataset must preserve a genuine unknown so the agent can report it."""
    with_cause = {inc for inc, _, _ in data.INCIDENT_CAUSE}
    affected = {inc for inc, _, _ in data.INCIDENT_AFFECTED}

    assert "inc-2026-04-webhook-latency" in affected
    assert "inc-2026-04-webhook-latency" not in with_cause


# --------------------------------------------------------------------------
# Traversal limits
# --------------------------------------------------------------------------


def test_depth_is_clamped_to_configured_ceiling():
    assert queries.max_depth(99) == queries.max_depth(None)
    assert queries.max_depth(0) == 1
    assert queries.max_depth(2) == 2


def test_result_limit_is_clamped():
    from app.config import get_settings

    assert queries.default_limit(500) == get_settings().graph_max_results
    assert queries.default_limit(5) == 5
    assert queries.default_limit(-5) == 1


def test_query_templates_are_parameterised():
    """No template may interpolate a value into the Cypher string."""

    for name, value in vars(queries).items():
        if not name.isupper() or not isinstance(value, str):
            continue
        # Only interpolation of module constants (labels/limit vars) is allowed.
        assert "{{" not in value, f"{name} contains a runtime interpolation"


# --------------------------------------------------------------------------
# Dependency impact (in-memory reference model)
# --------------------------------------------------------------------------


class TestDependencyImpact:
    def test_direct_consumers_are_depth_one(self, fake_repo):
        impacted = fake_repo.impacted_services("svc-payment-legacy")
        depth_one = {i.service.id for i in impacted if i.depth == 1}
        assert "svc-checkout" in depth_one
        assert "svc-invoice" in depth_one
        assert "svc-order" in depth_one
        assert "svc-subscription" in depth_one
        assert "svc-refunds" in depth_one

    def test_multi_hop_reaches_storefront_at_depth_three(self, fake_repo):
        """Storefront -> Cart -> Checkout -> Payment A is the demo's key path."""
        impacted = fake_repo.impacted_services("svc-payment-legacy")
        by_id = {i.service.id: i for i in impacted}

        assert by_id["svc-cart"].depth == 2
        assert by_id["svc-storefront"].depth == 3
        assert by_id["svc-promo"].depth == 3

    def test_depth_limit_is_respected(self, fake_repo):
        shallow = fake_repo.impacted_services("svc-payment-legacy", depth=1)
        assert all(i.depth <= 1 for i in shallow)
        assert {i.service.id for i in shallow} == {
            "svc-checkout", "svc-order", "svc-invoice",
            "svc-subscription", "svc-refunds",
        }

    def test_upstream_dependencies_are_not_reported_as_impacted(self, fake_repo):
        """Ledger and fraud are depended ON by payments, so they are not impacted."""
        impacted_ids = {i.service.id for i in fake_repo.impacted_services("svc-payment-legacy")}
        assert "svc-ledger" not in impacted_ids
        assert "svc-fraud" not in impacted_ids

    def test_unknown_service_returns_empty(self, fake_repo):
        assert fake_repo.impacted_services("svc-nope") == []

    def test_impacted_services_carry_owners(self, fake_repo):
        impacted = fake_repo.impacted_services("svc-payment-legacy")
        checkout = next(i for i in impacted if i.service.id == "svc-checkout")
        assert checkout.owners, "impacted service must surface its owner"
        assert any(p.id == "per-lena-fischer" for p in checkout.owners)


# --------------------------------------------------------------------------
# Ownership and engineers
# --------------------------------------------------------------------------


class TestOwnership:
    def test_owner_lookup(self, fake_repo):
        owners = fake_repo.owners_for(["svc-payment-legacy"])
        assert owners["svc-payment-legacy"][0].id == "per-amara-osei"

    def test_service_without_owner_is_omitted(self, fake_repo):
        owners = fake_repo.owners_for(["svc-checkout", "svc-does-not-exist"])
        assert "svc-checkout" in owners
        assert "svc-does-not-exist" not in owners

    def test_engineers_have_real_project_history(self, fake_repo):
        rows = fake_repo.relevant_engineers(["svc-payment-legacy"])
        assert rows, "expected engineers with project history"
        assert all("person_id" in r and "project_id" in r for r in rows)


# --------------------------------------------------------------------------
# Incidents, decisions, documents
# --------------------------------------------------------------------------


class TestIncidentsDecisionsDocuments:
    def test_related_incidents_expose_cause_only_when_recorded(self, fake_repo):
        rows = fake_repo.related_incidents(
            ["svc-webhook", "svc-payment-legacy", "svc-fraud"]
        )
        by_id = {r["id"]: r for r in rows}

        assert by_id["inc-2025-07-legacypay-key-rotation"]["cause_names"]
        assert by_id["inc-2026-04-webhook-latency"]["cause_names"] == []

    def test_decision_history_is_newest_first(self, fake_repo):
        rows = fake_repo.decision_history(["svc-payment-legacy"])
        dates = [r["date"] for r in rows]
        assert dates == sorted(dates, reverse=True)

    def test_superseded_decision_is_flagged(self, fake_repo):
        rows = fake_repo.decision_history(["svc-payment-legacy"])
        by_id = {r["id"]: r for r in rows}
        assert by_id["dec-2023-06-legacypay-adoption"]["superseded_by_ids"] == [
            "dec-2025-08-payments-modernization"
        ]

    def test_supporting_documents_resolve(self, fake_repo):
        rows = fake_repo.supporting_documents(["svc-payment-v2"])
        titles = {r["title"] for r in rows}
        assert "Payment Service B Gap Analysis" in titles

    def test_document_for_unknown_entity_is_empty(self, fake_repo):
        assert fake_repo.supporting_documents(["svc-nope"]) == []


# --------------------------------------------------------------------------
# Shared dependencies (the migration risk surface)
# --------------------------------------------------------------------------


class TestSharedDependencies:
    def test_shared_dependencies_found(self, fake_repo):
        shared = fake_repo.shared_dependencies("svc-payment-legacy", "svc-payment-v2")
        shared_ids = {s["id"] for s in shared}
        assert "svc-ledger" in shared_ids
        assert "svc-fraud" in shared_ids
        assert "svc-webhook" in shared_ids

    def test_identity_is_a_gap_in_service_b(self, fake_repo):
        """LegacyPay uses Identity; PayFlow does not. The graph must show that."""
        legacy_deps = {d["id"] for d in fake_repo.upstream_dependencies("svc-payment-legacy")}
        v2_deps = {d["id"] for d in fake_repo.upstream_dependencies("svc-payment-v2")}

        assert "svc-identity" in legacy_deps
        assert "svc-identity" not in v2_deps


# --------------------------------------------------------------------------
# Live FalkorDB parity (skipped when unavailable)
# --------------------------------------------------------------------------


@pytest.mark.integration
class TestLiveFalkorDB:
    def test_counts_match_seed(self, integration):
        from app.graph.repository import GraphRepository

        overview = GraphRepository().overview()
        assert overview["node_counts"].get("Service") == len(data.SERVICES)
        assert overview["node_counts"].get("Person") == len(data.PEOPLE)
        assert overview["total_relationships"] == len(data.all_relationships())

    def test_impact_matches_reference_model(self, integration):
        from app.graph.repository import GraphRepository

        repo = GraphRepository()
        impacted = repo.impacted_services("svc-payment-legacy")
        assert {i.service.id for i in impacted} == {
            "svc-checkout", "svc-order", "svc-invoice", "svc-subscription",
            "svc-refunds", "svc-cart", "svc-storefront", "svc-promo",
        }
        depths = {i.service.id: i.depth for i in impacted}
        assert depths["svc-cart"] == 2
        assert depths["svc-storefront"] == 3

    def test_unknown_cause_is_absent_from_graph(self, integration):
        from app.graph.repository import GraphRepository

        rows = GraphRepository().related_incidents(["svc-webhook"])
        unknown = next(r for r in rows if r["id"] == "inc-2026-04-webhook-latency")
        assert unknown["cause_names"] == []