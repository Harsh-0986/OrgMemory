"""Ingestion tests.

The model is never called. `extract_graph` and `ingest_document` both take an
`invoke` seam, so these tests drive the real pipeline - conversion, validation,
writing - with a scripted model response. That means the interesting behaviour
(invented labels, dangling relationships, existing entities being preserved) is
tested without spending any quota, and the tests do not care which provider or
model is configured.
"""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from app.ingest import (
    ExtractionOutcome,
    UnsupportedDocument,
    ingest_document,
    to_markdown,
    validate_extraction,
)
from app.ingest.service import document_id_for

# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------


class TestConversion:
    def test_markdown_passes_through(self):
        result = to_markdown("notes.md", b"# Title\n\nBody text.")
        assert result.markdown.startswith("# Title")
        assert "Body text." in result.markdown

    def test_html_is_converted_to_markdown(self):
        result = to_markdown("page.html", b"<h1>Doc</h1><p>Some body</p>")
        assert "# Doc" in result.markdown
        assert "Some body" in result.markdown

    def test_plain_text_is_accepted(self):
        result = to_markdown("notes.txt", b"just some words")
        assert "just some words" in result.markdown

    def test_a_docx_round_trips(self):
        """The office formats are the reason MarkItDown is here, not just .txt."""
        import io

        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_heading("Payments Runbook", level=1)
        document.add_paragraph("The Ledger Service depends on the Checkout API.")
        buffer = io.BytesIO()
        document.save(buffer)

        result = to_markdown("runbook.docx", buffer.getvalue())
        assert "Payments Runbook" in result.markdown
        assert "Ledger Service" in result.markdown

    def test_an_empty_file_is_refused_with_a_readable_message(self):
        with pytest.raises(UnsupportedDocument, match="empty"):
            to_markdown("notes.md", b"")

    def test_an_unsupported_extension_is_refused(self):
        with pytest.raises(UnsupportedDocument, match="not supported"):
            to_markdown("archive.zip", b"PK\x03\x04")

    def test_an_oversized_file_is_refused(self):
        with pytest.raises(UnsupportedDocument, match="larger than"):
            to_markdown("big.md", b"x" * (9 * 1024 * 1024))

    def test_a_file_with_no_readable_text_is_refused(self):
        with pytest.raises(UnsupportedDocument, match="converted to no text"):
            to_markdown("blank.txt", b"   \n  \n ")

    def test_long_documents_are_truncated_on_a_paragraph_boundary(self):
        paragraph = "word " * 40
        text = "\n\n".join([paragraph] * 400).encode()
        result = to_markdown("long.md", text)
        assert result.truncated
        assert not result.markdown.endswith("wor"), "cut mid-word"

    def test_supported_extensions_are_reported(self):
        from app.ingest import SUPPORTED_EXTENSIONS

        assert {".pdf", ".docx", ".md"} <= SUPPORTED_EXTENSIONS


# --------------------------------------------------------------------------
# Validation - the security boundary
# --------------------------------------------------------------------------


class TestExtractionValidation:
    def test_a_valid_extraction_is_kept(self):
        out = validate_extraction(
            {
                "summary": "a runbook",
                "entities": [
                    {"id": "svc-ledger", "type": "Service", "name": "Ledger Service"}
                ],
                "relationships": [
                    {"from_id": "svc-ledger", "type": "DEPENDS_ON", "to_id": "svc-checkout"}
                ],
            },
            known_ids={"svc-checkout"},
        )
        assert [e.id for e in out.entities] == ["svc-ledger"]
        assert len(out.relationships) == 1
        assert not out.rejected

    def test_an_invented_label_is_refused(self):
        out = validate_extraction(
            {
                "entities": [{"id": "x", "type": "Database", "name": "X"}],
                "relationships": [],
            },
            known_ids=set(),
        )
        assert out.entities == []
        assert "unknown label" in out.rejected[0].reason

    def test_an_invented_relationship_type_is_refused(self):
        out = validate_extraction(
            {
                "entities": [{"id": "svc-a", "type": "Service", "name": "A"}],
                "relationships": [
                    {"from_id": "svc-a", "type": "KNOWS", "to_id": "svc-a"}
                ],
            },
            known_ids=set(),
        )
        assert out.relationships == []
        assert "unknown relationship type" in out.rejected[0].reason

    def test_a_relationship_to_an_unknown_entity_is_refused(self):
        """This is what keeps "never invent relationships" true with a model."""
        out = validate_extraction(
            {
                "entities": [{"id": "svc-a", "type": "Service", "name": "A"}],
                "relationships": [
                    {"from_id": "svc-a", "type": "DEPENDS_ON", "to_id": "svc-ghost"}
                ],
            },
            known_ids=set(),
        )
        assert out.relationships == []
        assert "neither in this document nor in the graph" in out.rejected[0].reason

    def test_a_relationship_to_an_existing_entity_is_allowed(self):
        out = validate_extraction(
            {
                "entities": [{"id": "svc-a", "type": "Service", "name": "A"}],
                "relationships": [
                    {"from_id": "svc-a", "type": "DEPENDS_ON", "to_id": "svc-existing"}
                ],
            },
            known_ids={"svc-existing"},
        )
        assert len(out.relationships) == 1

    def test_self_relationships_are_refused(self):
        out = validate_extraction(
            {
                "entities": [{"id": "svc-a", "type": "Service", "name": "A"}],
                "relationships": [
                    {"from_id": "svc-a", "type": "DEPENDS_ON", "to_id": "svc-a"}
                ],
            },
            known_ids=set(),
        )
        assert out.relationships == []
        assert "itself" in out.rejected[0].reason

    def test_ids_are_slugified(self):
        out = validate_extraction(
            {
                "entities": [
                    {"id": "Ledger Service!!", "type": "Service", "name": "Ledger"}
                ],
                "relationships": [],
            },
            known_ids=set(),
        )
        assert out.entities[0].id == "ledger-service"

    def test_duplicate_entities_collapse(self):
        out = validate_extraction(
            {
                "entities": [
                    {"id": "svc-a", "type": "Service", "name": "A"},
                    {"id": "svc-a", "type": "Service", "name": "A again"},
                ],
                "relationships": [],
            },
            known_ids=set(),
        )
        assert len(out.entities) == 1

    def test_duplicate_relationships_collapse(self):
        payload = {
            "entities": [{"id": "svc-a", "type": "Service", "name": "A"}],
            "relationships": [
                {"from_id": "svc-a", "type": "DEPENDS_ON", "to_id": "svc-b"},
                {"from_id": "svc-a", "type": "DEPENDS_ON", "to_id": "svc-b"},
            ],
        }
        out = validate_extraction(payload, known_ids={"svc-b"})
        assert len(out.relationships) == 1

    def test_junk_shapes_are_refused_not_crashed_on(self):
        out = validate_extraction(
            {"entities": ["not-a-dict", 42, None], "relationships": ["nope"]},
            known_ids=set(),
        )
        assert out.entities == []
        assert out.relationships == []
        assert len(out.rejected) == 4

    def test_missing_lists_are_tolerated(self):
        out = validate_extraction({}, known_ids=set())
        assert out.entities == []
        assert out.relationships == []
        assert not out.rejected

    def test_an_entity_without_a_usable_id_is_refused(self):
        out = validate_extraction(
            {"entities": [{"id": "!!!", "type": "Service", "name": ""}]},
            known_ids=set(),
        )
        assert out.entities == []
        assert "no usable id" in out.rejected[0].reason

    def test_entity_count_is_capped(self):
        from app.ingest.extract import MAX_ENTITIES

        out = validate_extraction(
            {
                "entities": [
                    {"id": f"svc-{i}", "type": "Service", "name": str(i)}
                    for i in range(MAX_ENTITIES + 10)
                ]
            },
            known_ids=set(),
        )
        assert len(out.entities) == MAX_ENTITIES
        assert any("more than" in r.reason for r in out.rejected)


# --------------------------------------------------------------------------
# Extraction without a model call
# --------------------------------------------------------------------------


class TestExtractionWiring:
    def test_a_scripted_model_response_is_parsed_and_validated(self):
        from app.ingest import extract_graph

        def fake_invoke(system, user, timeout):  # noqa: ANN001, ANN202
            assert "Document title: Runbook" in user
            return json.dumps(
                {
                    "summary": "ledger runbook",
                    "entities": [
                        {"id": "svc-ledger", "type": "Service", "name": "Ledger"}
                    ],
                    "relationships": [
                        {
                            "from_id": "svc-ledger",
                            "type": "DEPENDS_ON",
                            "to_id": "svc-checkout",
                        }
                    ],
                }
            )

        out = extract_graph(
            "Runbook",
            "The Ledger Service depends on Checkout.",
            {"svc-checkout": "Checkout API"},
            invoke=fake_invoke,
        )
        assert out.model_used
        assert out.summary == "ledger runbook"
        assert [e.id for e in out.entities] == ["svc-ledger"]

    def test_existing_entities_are_offered_to_the_model(self):
        from app.ingest import extract_graph

        seen: dict[str, str] = {}

        def fake_invoke(system, user, timeout):  # noqa: ANN001, ANN202
            seen["user"] = user
            return "{}"

        extract_graph(
            "t",
            "c",
            {"svc-ledger": "Ledger Service"},
            invoke=fake_invoke,
        )
        assert "svc-ledger - Ledger Service" in seen["user"]

    def test_the_allowlists_are_stated_in_the_prompt(self):
        from app.ingest.extract import RELATION_TYPES, build_prompt

        system, _ = build_prompt("t", "c", {})
        for rel in RELATION_TYPES:
            assert rel in system
        assert "Investigation" not in system

    def test_no_model_yields_an_empty_flagged_result(self):
        from app.ingest import extract_graph

        out = extract_graph("t", "c", {}, invoke=lambda *a, **k: "")
        assert out.model_used is False
        assert out.entities == []

    def test_unparseable_model_output_is_reported_not_dropped(self):
        from app.ingest import extract_graph

        out = extract_graph("t", "c", {}, invoke=lambda *a, **k: "I think maybe yes?")
        assert out.model_used is True
        assert out.entities == []
        assert "not valid JSON" in out.rejected[0].reason


# --------------------------------------------------------------------------
# End to end against the in-memory repository
# --------------------------------------------------------------------------


def _scripted(payload: dict) -> object:
    def invoke(system, user, timeout):  # noqa: ANN001, ANN202
        return json.dumps(payload)

    return invoke


class TestIngestDocument:
    def test_pasted_text_creates_a_document_node(self, fake_repo):
        report = ingest_document(
            repository=fake_repo,
            text="A note about the Ledger Service.",
            title="Ledger note",
            source_type="note",
            invoke=_scripted({"entities": [], "relationships": []}),
        )
        assert report.document_id.startswith("doc-ingested-")
        assert report.title == "Ledger note"
        assert report.model_used

    def test_new_entities_are_created_and_reported(self, fake_repo):
        report = ingest_document(
            repository=fake_repo,
            text="The Payments Gateway service exists.",
            title="Gateway",
            invoke=_scripted(
                {
                    "summary": "gateway",
                    "entities": [
                        {
                            "id": "svc-payments-gateway",
                            "type": "Service",
                            "name": "Payments Gateway",
                        }
                    ],
                    "relationships": [],
                }
            ),
        )
        assert [e.id for e in report.entities_created] == ["svc-payments-gateway"]
        assert report.entities_created[0].type == "Service"

    def test_an_existing_entity_is_linked_not_rewritten(self, fake_repo):
        """A model misreading a sentence must not overwrite curated data."""
        fakes = fake_repo
        before = fakes.get_entity("svc-checkout")

        report = ingest_document(
            repository=fakes,
            text="Checkout API is a payments thing.",
            title="Checkout",
            invoke=_scripted(
                {
                    "entities": [
                        {
                            "id": "svc-checkout",
                            "type": "Service",
                            "name": "WRONG NAME",
                            "properties": {"criticality": "low"},
                        }
                    ],
                    "relationships": [],
                }
            ),
        )

        assert report.entities_created == []
        assert [e.id for e in report.entities_linked] == ["svc-checkout"]
        after = fakes.get_entity("svc-checkout")
        assert after == before, "an existing entity was modified by an upload"

    def test_relationships_are_written_and_reported(self, fake_repo):
        report = ingest_document(
            repository=fake_repo,
            text="x",
            title="rel",
            invoke=_scripted(
                {
                    "entities": [
                        {"id": "svc-new", "type": "Service", "name": "New"}
                    ],
                    "relationships": [
                        {"from_id": "svc-new", "type": "DEPENDS_ON", "to_id": "svc-checkout"}
                    ],
                }
            ),
        )
        assert report.relationships_created == ["svc-new -DEPENDS_ON-> svc-checkout"]

    def test_the_document_gets_provenance_edges(self, fake_repo):
        """Written even when the model proposed no relationships at all."""
        report = ingest_document(
            repository=fake_repo,
            text="x",
            title="prov",
            invoke=_scripted(
                {
                    "entities": [
                        {"id": "svc-prov", "type": "Service", "name": "Prov"}
                    ],
                    "relationships": [],
                }
            ),
        )
        assert report.citations_linked >= 1
        assert fake_repo.links_for(report.document_id) == ["svc-prov"]

    def test_rejections_are_surfaced_in_the_report(self, fake_repo):
        report = ingest_document(
            repository=fake_repo,
            text="x",
            title="bad",
            invoke=_scripted(
                {
                    "entities": [{"id": "x", "type": "Database", "name": "X"}],
                    "relationships": [],
                }
            ),
        )
        assert report.rejected
        assert report.entities_created == []

    def test_no_model_still_ingests_the_document(self, fake_repo):
        """A document must be storable and citable with no model at all."""
        report = ingest_document(
            repository=fake_repo,
            text="Some content that a search can find later.",
            title="offline note",
            invoke=lambda *a, **k: "",
        )
        assert report.model_used is False
        assert report.document_id.startswith("doc-ingested-")

    def test_the_same_content_yields_the_same_id(self):
        assert document_id_for("t", "body") == document_id_for("t", "body")
        assert document_id_for("t", "body") != document_id_for("t", "other")

    def test_a_pasted_document_is_titled_from_its_first_line(self, fake_repo):
        """No filename and no title: the author's own heading is the title."""
        report = ingest_document(
            repository=fake_repo,
            text="# Payments Runbook\n\nHow to reconcile the ledger.",
            invoke=lambda *a, **k: "{}",
        )
        assert report.title == "Payments Runbook"

    def test_a_title_still_wins_over_the_first_line(self, fake_repo):
        report = ingest_document(
            repository=fake_repo,
            text="# Payments Runbook\n\nBody.",
            title="Ledger notes",
            invoke=lambda *a, **k: "{}",
        )
        assert report.title == "Ledger notes"

    def test_an_untitled_filename_is_tidied_into_a_title(self, fake_repo):
        """`payments_runbook.md` should read as "payments runbook"."""
        report = ingest_document(
            repository=fake_repo,
            filename="payments_runbook.md",
            data=b"Body with no heading.",
            invoke=lambda *a, **k: "{}",
        )
        assert report.title == "payments runbook"

    def test_an_unknown_source_type_falls_back(self, fake_repo):
        report = ingest_document(
            repository=fake_repo,
            text="x",
            title="t",
            source_type="nonsense",
            invoke=lambda *a, **k: "{}",
        )
        assert report.source_type == "upload"

    def test_a_non_string_property_is_stored_not_dropped(self, fake_repo):
        """FalkorDB holds primitives; anything else becomes text, not nothing."""
        report = ingest_document(
            repository=fake_repo,
            text="x",
            title="props",
            invoke=_scripted(
                {
                    "entities": [
                        {
                            "id": "svc-props",
                            "type": "Service",
                            "name": "Props",
                            "properties": {"nested": {"a": 1}, "list_of_dicts": [{"b": 2}]},
                        }
                    ],
                    "relationships": [],
                }
            ),
        )
        stored = fake_repo.get_entity("svc-props")
        assert report.entities_created
        assert isinstance(stored["properties"].get("nested"), str)


class TestIngestionSchemaInterlock:
    """The label/rel-type slots are only safe because these refuse everything."""

    def test_ingestion_refuses_a_label_that_is_not_in_the_schema(self, fake_repo):
        with pytest.raises(ValueError, match="unknown entity label"):
            fake_repo.upsert_entities(
                [{"id": "x", "type": "Service; MATCH (n) DETACH DELETE n", "properties": {}}]
            )

    def test_ingestion_refuses_a_relationship_type_not_in_the_schema(self, fake_repo):
        with pytest.raises(ValueError, match="unknown relationship type"):
            fake_repo.upsert_relationships(
                [{"from_id": "svc-a", "type": "DROP", "to_id": "svc-b"}]
            )

    def test_investigation_is_not_an_ingestable_label(self, fake_repo):
        """Only the agent may create Investigations, never a document."""
        with pytest.raises(ValueError, match="unknown entity label"):
            fake_repo.upsert_entities(
                [{"id": "inv-x", "type": "Investigation", "properties": {}}]
            )


@pytest.fixture
def ingest_jobs_registry():
    """Keep the process-wide job registry from leaking between tests."""
    from app.ingest import jobs as ingest_jobs

    ingest_jobs.registry.clear()
    yield ingest_jobs.registry
    ingest_jobs.registry.clear()


class TestIngestApi:
    """The synchronous path, reached with `?wait=true`.

    Queued ingestion is the default (see `TestIngestJobs`). The waiting path is
    not merely a test convenience - it is what a script or a curl call wants -
    and exercising it here means the two paths cannot quietly diverge.
    """

    def test_capabilities_are_reported(self, client):
        body = client.get("/api/ingest/capabilities").json()
        assert ".md" in body["supported_extensions"]
        assert body["max_upload_bytes"] > 0
        assert isinstance(body["model_available"], bool)

    def test_text_ingestion_via_http(self, client):
        """The route works with no model available, which is the test default.

        A model-free ingest is worth asserting on its own: the document must
        still be stored and citable, and `model_used` must say so honestly.
        """
        response = client.post(
            "/api/ingest/text?wait=true",
            json={"title": "Note", "content": "Something about a service."},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["document_id"].startswith("doc-ingested-")
        assert body["model_used"] is False

    def test_a_bad_file_is_a_400_with_a_readable_message(self, client):
        response = client.post(
            "/api/ingest/file?wait=true",
            files={"file": ("archive.zip", b"PK\x03\x04", "application/zip")},
        )
        assert response.status_code == 400
        error = response.json()["error"]
        assert error["code"] == "bad_request"
        assert "not supported" in error["message"]

    def test_file_ingestion_succeeds_and_returns_a_report(self, client):
        response = client.post(
            "/api/ingest/file?wait=true",
            files={"file": ("note.md", b"# Note\n\nAbout the Ledger.", "text/markdown")},
        )
        assert response.status_code == 200, response.text
        assert response.json()["title"] == "note"

    def test_an_empty_upload_is_a_400(self, client):
        response = client.post(
            "/api/ingest/file?wait=true",
            files={"file": ("note.md", b"", "text/markdown")},
        )
        assert response.status_code == 400

    def test_an_oversized_upload_is_refused_before_it_is_read(self, client, monkeypatch):
        """The size is known from the part header, so say no without reading it.

        The limit is patched down rather than uploading 8MB, which would make the
        suite slow without testing anything the small payload does not.
        """
        monkeypatch.setattr("app.api.routes.ingest.MAX_UPLOAD_BYTES", 64)

        response = client.post(
            "/api/ingest/file?wait=true",
            files={"file": ("big.md", b"x" * 500, "text/markdown")},
        )

        assert response.status_code == 413
        error = response.json()["error"]
        assert error["code"] == "payload_too_large"
        assert "larger than" in error["message"]


class TestIngestJobs:
    """Queued ingestion: POST answers at once, the client polls for progress.

    The reason to queue is that extraction is a model call that can take minutes.
    Holding the connection open for it means one opaque spinner and a request
    that a proxy may well kill first; queueing means the same wait, with the
    phases visible as they finish.
    """

    def test_an_upload_is_queued_rather_than_held_open(self, client, ingest_jobs_registry):
        response = client.post(
            "/api/ingest/file",
            files={
                "file": (
                    "payments_runbook.md",
                    b"# Payments Runbook\n\nAbout the Ledger.",
                    "text/markdown",
                )
            },
        )

        assert response.status_code == 202, response.text
        body = response.json()
        assert body["job_id"].startswith("ing-")
        assert body["poll_url"] == f"/api/ingest/{body['job_id']}/status"
        # The title is the one the document will actually end up with, derived
        # the same way `ingest_document` derives it. A queued upload can say what
        # it is about before it has read a word of it.
        assert body["title"] == "payments runbook"

    def test_polling_reaches_the_report(self, client, ingest_jobs_registry):
        accepted = client.post(
            "/api/ingest/text",
            json={"title": "Note", "content": "Something about a service."},
        ).json()

        status = client.get(accepted["poll_url"]).json()

        assert status["done"] is True
        assert status["status"] == "completed"
        assert status["error"] is None
        assert status["finished_at"] is not None
        assert status["result"]["document_id"].startswith("doc-ingested-")

    def test_each_phase_is_published_as_it_finishes(self, client, ingest_jobs_registry):
        accepted = client.post(
            "/api/ingest/text",
            json={"title": "Note", "content": "Something about a service."},
        ).json()

        steps = client.get(accepted["poll_url"]).json()["steps"]

        assert [step["phase"] for step in steps] == ["convert", "extract", "write"]
        assert all(step["duration_ms"] >= 0 for step in steps)
        # The extraction step has to admit that no model was available, because
        # "the document had no entities" and "nothing looked" are different
        # results and only one of them is the document's fault.
        extract = next(step for step in steps if step["phase"] == "extract")
        assert "No model available" in extract["title"]

    def test_the_read_step_reports_what_it_found(self, client, ingest_jobs_registry, monkeypatch):
        """Once a model is in play, the step counts what came back."""

        def fake_extract(title, markdown, known=None, *, invoke=None):  # noqa: ANN001, ANN202
            return ExtractionOutcome(
                model_used=True,
                entities=[
                    {"id": "svc-x", "type": "Service", "name": "X Service"},
                ],
                relationships=[],
            )

        monkeypatch.setattr("app.ingest.service.extract_graph", fake_extract)

        accepted = client.post(
            "/api/ingest/text",
            json={"title": "Note", "content": "Something about a service."},
        ).json()
        steps = client.get(accepted["poll_url"]).json()["steps"]
        extract = next(step for step in steps if step["phase"] == "extract")

        assert extract["title"] == "Read the document for entities"
        assert "1 entities" in extract["detail"]

    def test_a_failed_ingestion_is_reported_not_lost(
        self, client, ingest_jobs_registry, monkeypatch
    ):
        def explode(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise ValueError("The reader returned something unreadable.")

        monkeypatch.setattr("app.ingest.service.extract_graph", explode)

        accepted = client.post(
            "/api/ingest/text",
            json={"title": "Note", "content": "Something about a service."},
        ).json()
        status = client.get(accepted["poll_url"]).json()

        assert status["status"] == "failed"
        assert status["done"] is True
        assert status["result"] is None
        # The message is shown to the user verbatim, so it must be the reason
        # rather than a repr of the exception.
        assert "unreadable" in status["error"]

    def test_an_unknown_job_is_a_404(self, client, ingest_jobs_registry):
        """A job lost to a restart must read as absent, not as running forever."""
        response = client.get("/api/ingest/ing-doesnotexist/status")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


class TestIngestDoesNotBlockTheServer:
    """The bug this guards against: one upload freezing the whole API.

    Ingestion is synchronous and can take minutes, because extraction is a model
    call. The `/file` route must be `async def` to read the upload, so if the
    pipeline runs inline it runs *on the event loop* - and the event loop is the
    only thread serving every other request. The symptom was that uploading a
    document made every other endpoint hang for as long as the upload took.

    Both paths need guarding. The queued path hands work to the background thread
    pool by construction, but `?wait=true` runs the pipeline from inside the
    route, where "it is only one call" is exactly the reasoning that broke it.

    These tests assert latency rather than the presence of `run_in_threadpool`,
    because latency is the thing that was broken.
    """

    @staticmethod
    def _slow_pipeline(monkeypatch, seconds: float = 1.0) -> None:
        """Stand in for a slow model, without calling one."""

        def slow_extract(title, markdown, known=None, *, invoke=None):  # noqa: ANN001, ANN202
            time.sleep(seconds)
            return ExtractionOutcome(model_used=True)

        monkeypatch.setattr("app.ingest.service.extract_graph", slow_extract)

    @staticmethod
    def _app(fake_repo, monkeypatch):  # noqa: ANN001, ANN202
        from app.api import deps
        from app.main import create_app

        app = create_app()
        app.dependency_overrides[deps.get_repository] = lambda: fake_repo
        # Keep /health off a real FalkorDB instance.
        monkeypatch.setattr("app.api.routes.health.graph_client.ping", lambda: True)
        return app

    async def _slow_upload_against_a_free_loop(self, app, url: str) -> httpx.Response:
        """Start a slow ingest and prove the event loop kept running."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            upload = asyncio.create_task(
                client.post(
                    url,
                    files={"file": ("note.md", b"# Note\n\nBody.", "text/markdown")},
                )
            )

            # The signal is timer accuracy, not a stopwatch around one request.
            # A free event loop returns from this sleep on time; a blocked one
            # cannot fire the timer until the blocking call finishes, so the
            # overshoot *is* the blockage. Timing a request afterwards would
            # measure nothing, because by then the block is already over.
            started = time.perf_counter()
            await asyncio.sleep(0.15)
            overshoot = time.perf_counter() - started - 0.15

            assert overshoot < 0.5, (
                f"the event loop stalled for {overshoot:.2f}s while an upload was "
                "in flight: blocking work is running on the loop, not a worker thread"
            )

            # And unrelated requests must be served promptly in the meantime.
            started = time.perf_counter()
            health = await client.get("/health")
            elapsed = time.perf_counter() - started

            assert health.status_code == 200
            assert elapsed < 0.5, f"/health took {elapsed:.2f}s while an upload was in flight"

            return await upload

    async def test_a_queued_upload_does_not_stall_the_loop(
        self, fake_repo, ingest_jobs_registry, monkeypatch
    ):
        self._slow_pipeline(monkeypatch)
        response = await self._slow_upload_against_a_free_loop(
            self._app(fake_repo, monkeypatch), "/api/ingest/file"
        )

        assert response.status_code == 202, response.text

    async def test_a_waiting_upload_does_not_stall_the_loop(
        self, fake_repo, monkeypatch
    ):
        self._slow_pipeline(monkeypatch)
        response = await self._slow_upload_against_a_free_loop(
            self._app(fake_repo, monkeypatch), "/api/ingest/file?wait=true"
        )

        assert response.status_code == 200, response.text

    async def test_a_slow_upload_still_returns_its_report(self, fake_repo, monkeypatch):
        """The fix must not turn a slow upload into a failed one."""
        self._slow_pipeline(monkeypatch, seconds=0.3)
        app = self._app(fake_repo, monkeypatch)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/ingest/file?wait=true",
                files={"file": ("note.md", b"# Note\n\nBody.", "text/markdown")},
            )

        assert response.status_code == 200, response.text
        assert response.json()["document_id"].startswith("doc-ingested-")
