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
        response = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION})
        assert response.status_code == 200
        body = response.json()

        assert body["status"] == "completed"
        assert body["intent"] == "replacement"
        assert body["answer"]
        assert "svc-payment-legacy" in body["answer"]

    def test_response_carries_evidence_and_paths(self, client):
        body = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION}).json()

        assert body["evidence"], "evidence records must be returned"
        assert body["graph_paths"], "dependency paths must be returned"
        assert all(e["tool"] for e in body["evidence"])

    def test_response_carries_impacted_services_with_owners(self, client):
        body = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION}).json()
        impacted = {s["service"]["id"]: s for s in body["impacted_services"]}

        assert impacted["svc-checkout"]["depth"] == 1
        assert impacted["svc-storefront"]["depth"] == 3
        assert any(p["id"] == "per-lena-fischer" for p in impacted["svc-checkout"]["owners"])

    def test_response_is_documented_by_execution_steps(self, client):
        body = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION}).json()
        nodes_ran = {s["node"] for s in body["steps"]}
        assert {"plan", "retrieve", "write", "critic", "memory"} <= nodes_ran

    def test_shared_dependencies_are_surfaced(self, client):
        body = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION}).json()
        shared = {s["id"] for s in body["shared_dependencies"]}
        assert {"svc-ledger", "svc-fraud", "svc-webhook"} <= shared

    def test_unknown_cause_is_reported_not_invented(self, client):
        body = client.post(
            "/api/investigations?wait=true", json={"question": "What incidents affected the Webhook Dispatcher?"},
        ).json()

        unknown = next(
            i for i in body["incidents"] if i["id"] == "inc-2026-04-webhook-latency"
        )
        assert unknown["cause_names"] == []
        assert "not recorded" in body["answer"].lower() or "unknown" in body["answer"].lower()

    def test_unresolvable_question_still_returns_200(self, client):
        response = client.post(
            "/api/investigations?wait=true", json={"question": "What is the marketing team's favourite colour?"},
        )
        assert response.status_code == 200
        assert response.json()["answer"]


# --------------------------------------------------------------------------
# Request validation
# --------------------------------------------------------------------------


class TestValidation:
    def test_question_is_required(self, client):
        response = client.post(
            "/api/investigations?wait=true", json={})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    def test_question_minimum_length(self, client):
        response = client.post(
            "/api/investigations?wait=true", json={"question": "why?"})
        assert response.status_code == 422

    def test_blank_question_is_rejected(self, client):
        response = client.post(
            "/api/investigations?wait=true", json={"question": "          "})
        assert response.status_code == 422

    def test_question_is_trimmed(self, client):
        response = client.post(
            "/api/investigations?wait=true", json={"question": f"   {DEMO_QUESTION}   "}
        )
        assert response.status_code == 200
        assert response.json()["question"] == DEMO_QUESTION

    def test_wrong_type_is_rejected(self, client):
        response = client.post(
            "/api/investigations?wait=true", json={"question": 12345})
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
        created = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION}).json()
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
        created = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION}).json()
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
        first = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION}).json()

        second_client = TestClient(create_app())
        second_client.app.dependency_overrides[deps.get_repository] = lambda: fake_repo
        history = second_client.get("/api/investigations/history").json()

        assert history["total"] == 1
        assert history["investigations"][0]["id"] == first["investigation_id"]

    def test_follow_up_question_recalls_earlier_investigation(self, client):
        first = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION}).json()
        second = client.post(
            "/api/investigations?wait=true", json={"question": "Who should review the Payment Service A replacement?"},
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

# --------------------------------------------------------------------------
# Asynchronous investigations
# --------------------------------------------------------------------------


class TestAsyncInvestigations:
    def test_post_returns_202_with_a_poll_url(self, client):
        response = client.post("/api/investigations", json={"question": DEMO_QUESTION})
        assert response.status_code == 202

        body = response.json()
        assert body["status"] in ("pending", "running", "completed")
        assert body["investigation_id"].startswith("inv-")
        assert body["poll_url"] == f"/api/investigations/{body['investigation_id']}"

    def test_answer_is_not_in_the_accepted_response(self, client):
        """Async means the answer is fetched, not blocked on."""
        body = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()
        assert "answer" not in body

    def test_status_endpoint_reports_a_terminal_state(self, client):
        accepted = client.post("/api/investigations", json={"question": DEMO_QUESTION}).json()

        # BackgroundTasks run after the response is returned, so poll briefly.
        deadline = 20
        body: dict = {}
        while deadline > 0:
            response = client.get(f"/api/investigations/{accepted['investigation_id']}/status")
            assert response.status_code == 200
            body = response.json()
            if body["done"]:
                break
            deadline -= 1
            __import__("time").sleep(0.25)

        assert body["done"], "investigation never reached a terminal state"
        assert body["status"] == "completed"
        assert body["result"] is not None

    def test_wait_true_still_returns_the_whole_answer(self, client):
        response = client.post("/api/investigations?wait=true", json={"question": DEMO_QUESTION})
        assert response.status_code == 200
        assert response.json()["answer"]

    def test_unknown_job_is_404(self, client):
        response = client.get("/api/investigations/inv-nope/status")
        assert response.status_code == 404

    def test_validation_applies_before_a_job_is_created(self, client):
        response = client.post("/api/investigations", json={"question": "x"})
        assert response.status_code == 422


class TestJobRegistry:
    """Unit tests for the store behind the async flow."""

    def test_append_step_does_not_deadlock(self):
        """Regression: append_step used to call get() while holding the lock.

        Both take the same non-reentrant lock, so a running investigation
        deadlocked the moment it published its first step.
        """
        import threading

        from app.agent.jobs import JobRegistry

        registry = JobRegistry()
        registry.create("inv-1", "q")

        finished = threading.Event()

        def worker() -> None:
            registry.append_step("inv-1", {"node": "retrieve", "title": "x"})
            finished.set()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        assert finished.wait(5), "append_step deadlocked on its own lock"
        assert registry.get("inv-1").steps == [{"node": "retrieve", "title": "x"}]

    def test_append_step_to_an_unknown_job_is_a_no_op(self):
        from app.agent.jobs import JobRegistry

        registry = JobRegistry()
        registry.append_step("inv-missing", {"node": "retrieve"})
        assert registry.get("inv-missing") is None


class TestLiveProgress:
    """Progress is published as the workflow runs, not collected at the end."""

    def test_run_investigation_calls_the_reporter(self, fake_repo):
        from app.agent.graph import run_investigation

        seen: list = []
        run_investigation(DEMO_QUESTION, repository=fake_repo, on_step=seen.append)

        assert seen, "no progress was published during the run"
        assert all(step.title for step in seen)

    def test_every_phase_is_announced(self, fake_repo):
        """The phases around model calls are the slow ones, so all must report."""
        from app.agent.graph import run_investigation

        seen: list = []
        run_investigation(DEMO_QUESTION, repository=fake_repo, on_step=seen.append)

        announced = {step.node for step in seen}
        assert {"plan", "retrieve", "assemble", "critic", "write", "memory"} <= announced

    def test_phase_announcements_are_not_stored_in_the_final_trace(self, fake_repo):
        """The published stream is transient; `steps` stays the durable trace."""
        from app.agent.graph import run_investigation

        seen: list = []
        state = run_investigation(
            DEMO_QUESTION, repository=fake_repo, on_step=seen.append
        )

        reported = [step for step in seen if step.status == "running"]
        assert reported, "expected some transient phase announcements"
        assert all(step.status != "running" for step in state.get("steps", []))

    def test_a_failing_reporter_cannot_break_the_investigation(self, fake_repo):
        """Progress is best-effort: reporting must never fail a real run."""
        from app.agent.graph import run_investigation

        def explode(step) -> None:  # noqa: ANN001 - deliberately hostile
            raise RuntimeError("reporter is broken")

        state = run_investigation(DEMO_QUESTION, repository=fake_repo, on_step=explode)
        assert state.get("status") == "completed"


# --------------------------------------------------------------------------
# LLM provider selection
# --------------------------------------------------------------------------


class TestProviderSelection:
    def test_explicit_nvidia_is_respected(self):
        from app.config import Settings
        from app.llm import resolve_provider

        settings = Settings(
            llm_provider="nvidia",
            nvidia_api_key="a",
            google_api_key="b",
            _env_file=None,
        )
        assert resolve_provider(settings) == "nvidia"

    def test_explicit_google_is_respected(self):
        from app.config import Settings
        from app.llm import resolve_provider

        settings = Settings(
            llm_provider="google",
            nvidia_api_key="a",
            google_api_key="b",
            _env_file=None,
        )
        assert resolve_provider(settings) == "google"

    def test_auto_prefers_nvidia_when_both_keys_exist(self):
        from app.config import Settings
        from app.llm import resolve_provider

        both = Settings(
            llm_provider="auto",
            nvidia_api_key="a",
            google_api_key="b",
            _env_file=None,
        )
        assert resolve_provider(both) == "nvidia"

    def test_auto_falls_back_to_google(self):
        from app.config import Settings
        from app.llm import resolve_provider

        only_google = Settings(llm_provider="auto", google_api_key="b", _env_file=None)
        assert resolve_provider(only_google) == "google"

    def test_no_keys_resolves_to_nothing(self):
        from app.config import Settings
        from app.llm import resolve_provider

        settings = Settings(llm_provider="auto", _env_file=None)
        assert resolve_provider(settings) is None

    def test_naming_a_provider_without_its_key_resolves_to_nothing(self):
        """Asking for Google without a Google key must not silently use NVIDIA."""
        from app.config import Settings
        from app.llm import resolve_provider

        settings = Settings(
            llm_provider="google", nvidia_api_key="a", _env_file=None
        )
        assert resolve_provider(settings) is None

    def test_describe_providers_lists_only_configured_ones(self):
        from app.config import Settings
        from app.llm import describe_providers

        assert describe_providers(Settings(nvidia_api_key="a", _env_file=None)) == [
            "nvidia"
        ]
        assert describe_providers(
            Settings(nvidia_api_key="a", google_api_key="b", _env_file=None)
        ) == ["nvidia", "google"]
        assert describe_providers(Settings(_env_file=None)) == []

    def test_disabling_the_llm_wins_over_a_present_key(self):
        from app.config import Settings
        from app.llm import LLMUnavailable, _build

        settings = Settings(llm_enabled=False, nvidia_api_key="a", _env_file=None)
        with pytest.raises(LLMUnavailable, match="disabled"):
            _build(settings)

    def test_missing_credentials_raise_rather_than_crash_later(self):
        from app.config import Settings
        from app.llm import LLMUnavailable, _build

        settings = Settings(llm_enabled=True, _env_file=None)
        with pytest.raises(LLMUnavailable, match="No LLM is configured"):
            _build(settings)

    def test_google_builds_the_real_gemini_client(self):
        """Google goes through `langchain-google-genai`, not an OpenAI shim.

        Constructing the client makes no network call, so this asserts the
        integration without spending any of the account's quota.
        """
        from langchain_google_genai import ChatGoogleGenerativeAI

        from app.config import Settings
        from app.llm import _build_google

        settings = Settings(
            google_api_key="not-a-real-key",
            google_model="gemini-3.8-flash",
            _env_file=None,
        )
        client = _build_google(settings)

        assert isinstance(client, ChatGoogleGenerativeAI)
        assert client.model == "gemini-3.8-flash"

    def test_google_without_a_key_is_refused(self):
        from app.config import Settings
        from app.llm import LLMUnavailable, _build_google

        with pytest.raises(LLMUnavailable, match="GOOGLE_API_KEY"):
            _build_google(Settings(_env_file=None))

    def test_health_reports_a_usable_provider(self, client):
        body = client.get("/health").json()
        assert isinstance(body["llm_configured"], bool)
