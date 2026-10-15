"""API tests.

The dependency is overridden with the in-memory repository, so the whole HTTP
surface is exercised without a database or a model.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.main import create_app

DEMO_QUESTION = (
    "Can we replace Payment Service A with Payment Service B? What could break, "
    "who should review it, and why do we use the current service?"
)


@pytest.fixture
def client(fake_repo, monkeypatch):
    """A TestClient whose repository is the in-memory one."""
    app = create_app()
    app.dependency_overrides[deps.get_repository] = lambda: fake_repo
    # Keep /health from probing a real FalkorDB instance.
    monkeypatch.setattr("app.api.routes.health.graph_client.ping", lambda: True)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------


class TestHealth:
    def test_health_reports_ok(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["app"] == "OrgMemory"

    def test_health_degrades_instead_of_failing(self, monkeypatch, fake_repo):
        """An unreachable graph must not take the service down."""
        monkeypatch.setattr("app.api.routes.health.graph_client.ping", lambda: False)
        app = create_app()
        app.dependency_overrides[deps.get_repository] = lambda: fake_repo
        with TestClient(app) as degraded:
            response = degraded.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "degraded"
        assert body["graph_connected"] is False

    def test_root_points_at_docs(self, client):
        assert client.get("/").json()["docs"] == "/docs"


# --------------------------------------------------------------------------
# Graph endpoints
# --------------------------------------------------------------------------


class TestGraphEndpoints:
    def test_overview_counts(self, client):
        from app.seed import data

        body = client.get("/api/graph/overview").json()
        assert body["node_counts"]["Service"] == len(data.SERVICES)
        assert body["node_counts"]["Person"] == len(data.PEOPLE)
        assert body["total_relationships"] == len(data.all_relationships())

    def test_overview_includes_criticality_mix(self, client):
        body = client.get("/api/graph/overview").json()
        assert body["criticality_breakdown"].get("critical", 0) > 0

    def test_neighborhood_requires_entity_id(self, client):
        response = client.get("/api/graph/neighborhood")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_neighborhood_validates_depth_bounds(self, client):
        response = client.get(
            "/api/graph/neighborhood", params={"entity_id": "svc-checkout", "depth": 99}
        )
        assert response.status_code == 422

    def test_neighborhood_for_unknown_entity_is_empty_not_404(self, client):
        response = client.get(
            "/api/graph/neighborhood", params={"entity_id": "svc-nope"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["nodes"] == []


# --------------------------------------------------------------------------
# Investigations
# --------------------------------------------------------------------------


class TestInvestigationEndpoint:
    def test_demo_question_returns_grounded_answer(self, client):
        response = client.post("/api/investigations", json={"question": DEMO_QUESTION})
        assert response.status_code == 200
        body = response.json()

        assert body["status"] == "completed"
        assert body["intent"] == "replacement"
        assert body["answer"]
        assert "svc-payment-legacy" in body["answer"]

    def test_response_carries_evidence_and_paths(self, client):
        body = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()

        assert body["evidence"], "evidence records must be returned"
        assert body["graph_paths"], "dependency paths must be returned"
        assert all(e["tool"] for e in body["evidence"])

    def test_response_carries_impacted_services_with_owners(self, client):
        body = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()
        impacted = {s["service"]["id"]: s for s in body["impacted_services"]}

        assert impacted["svc-checkout"]["depth"] == 1
        assert impacted["svc-storefront"]["depth"] == 3
        assert any(p["id"] == "per-lena-fischer" for p in impacted["svc-checkout"]["owners"])

    def test_response_is_documented_by_execution_steps(self, client):
        body = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()
        nodes_ran = {s["node"] for s in body["steps"]}
        assert {"plan", "retrieve", "write", "critic", "memory"} <= nodes_ran

    def test_shared_dependencies_are_surfaced(self, client):
        body = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()
        shared = {s["id"] for s in body["shared_dependencies"]}
        assert {"svc-ledger", "svc-fraud", "svc-webhook"} <= shared

    def test_unknown_cause_is_reported_not_invented(self, client):
        body = client.post(
            "/api/investigations",
            json={"question": "What incidents affected the Webhook Dispatcher?"},
        ).json()

        unknown = next(
            i for i in body["incidents"] if i["id"] == "inc-2026-04-webhook-latency"
        )
        assert unknown["cause_names"] == []
        assert "not recorded" in body["answer"].lower() or "unknown" in body["answer"].lower()

    def test_unresolvable_question_still_returns_200(self, client):
        response = client.post(
            "/api/investigations",
            json={"question": "What is the marketing team's favourite colour?"},
        )
        assert response.status_code == 200
        assert response.json()["answer"]


# --------------------------------------------------------------------------
# Request validation
# --------------------------------------------------------------------------


class TestValidation:
    def test_question_is_required(self, client):
        response = client.post("/api/investigations", json={})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_question_minimum_length(self, client):
        response = client.post("/api/investigations", json={"question": "why?"})
        assert response.status_code == 422

    def test_blank_question_is_rejected(self, client):
        response = client.post("/api/investigations", json={"question": "          "})
        assert response.status_code == 422

    def test_question_is_trimmed(self, client):
        response = client.post(
            "/api/investigations", json={"question": f"   {DEMO_QUESTION}   "}
        )
        assert response.status_code == 200
        assert response.json()["question"] == DEMO_QUESTION

    def test_wrong_type_is_rejected(self, client):
        response = client.post("/api/investigations", json={"question": 12345})
        assert response.status_code == 422


# --------------------------------------------------------------------------
# Memory endpoints
# --------------------------------------------------------------------------


class TestMemoryEndpoints:
    def test_history_is_empty_before_any_investigation(self, client):
        body = client.get("/api/investigations/history").json()
        assert body["total"] == 0
        assert body["investigations"] == []

    def test_investigation_is_persisted_and_retrievable(self, client):
        created = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()
        inv_id = created["investigation_id"]

        history = client.get("/api/investigations/history").json()
        assert history["total"] == 1
        assert history["investigations"][0]["id"] == inv_id
        assert history["investigations"][0]["question"] == DEMO_QUESTION

        detail = client.get(f"/api/investigations/{inv_id}").json()
        assert detail["id"] == inv_id
        assert detail["answer"] == created["answer"]
        assert detail["created_at"]

    def test_detail_includes_cited_entities_from_graph(self, client):
        created = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()
        detail = client.get(f"/api/investigations/{created['investigation_id']}").json()
        assert detail["cited_entities"], "citations must resolve to real graph nodes"

    def test_unknown_investigation_is_404(self, client):
        response = client.get("/api/investigations/inv-does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_history_route_is_not_shadowed_by_the_id_route(self, client):
        """`/history` must not be captured by `/{investigation_id}`."""
        response = client.get("/api/investigations/history")
        assert response.status_code == 200
        assert "investigations" in response.json()

    def test_memory_survives_a_fresh_session(self, client, fake_repo):
        """A new client reading the same store sees the earlier investigation."""
        first = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()

        second_client = TestClient(create_app())
        second_client.app.dependency_overrides[deps.get_repository] = lambda: fake_repo
        history = second_client.get("/api/investigations/history").json()

        assert history["total"] == 1
        assert history["investigations"][0]["id"] == first["investigation_id"]

    def test_follow_up_question_recalls_earlier_investigation(self, client):
        first = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()
        second = client.post(
            "/api/investigations",
            json={"question": "Who should review the Payment Service A replacement?"},
        ).json()

        recalled_ids = [r["id"] for r in second["recalled_investigations"]]
        assert first["investigation_id"] in recalled_ids


# --------------------------------------------------------------------------
# Error envelope
# --------------------------------------------------------------------------


class TestErrorEnvelope:
    def test_unknown_route_uses_standard_envelope(self, client):
        response = client.get("/api/nope")
        assert response.status_code == 404
        body = response.json()
        assert set(body["error"]) == {"code", "message", "detail"}

    def test_method_not_allowed_uses_standard_envelope(self, client):
        response = client.delete("/health")
        assert response.status_code == 405
        assert response.json()["error"]["code"] == "method_not_allowed"

    def test_openapi_documents_every_required_endpoint(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        for required in (
            "/health",
            "/api/graph/overview",
            "/api/graph/neighborhood",
            "/api/investigations",
            "/api/investigations/history",
            "/api/investigations/{investigation_id}",
        ):
            assert required in paths, f"{required} missing from the OpenAPI schema"