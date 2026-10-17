# Knowledge transfer — how OrgMemory actually works

Companion to [`HANDOFF.md`](./HANDOFF.md). That one gets you running; this one
explains the machinery, the reasoning behind it, and how to change it without
breaking the properties the product depends on.

Every claim here is checked against the code. File and line references are
deliberately sparse because they rot; names and paths are not.

---

## Contents

1. [Reading guide](#1-reading-guide)
2. [The graph](#2-the-graph)
3. [The query layer](#3-the-query-layer)
4. [The repository](#4-the-repository)
5. [The agent](#5-the-agent)
6. [LLM wiring](#6-llm-wiring)
7. [Document ingestion](#7-document-ingestion)
8. [The async job pattern](#8-the-async-job-pattern)
9. [The API surface](#9-the-api-surface)
10. [The frontend](#10-the-frontend)
11. [Testing](#11-testing)
12. [Decision log](#12-decision-log)
13. [Recipes](#13-recipes)
14. [Debugging playbook](#14-debugging-playbook)
15. [Where the remaining work is](#15-where-the-remaining-work-is)

---

## 1. Reading guide

The dependency direction is strictly one way:

```
models/graph.py  ─┬─▶  graph/{client,schema,queries,repository}  ─┬─▶  agent/{tools,nodes,graph}
                  │                                                │
models/api.py    ─┴─────────▶ api/routes/*  ◀──────────────────────┘
                                                                   │
models/ingest.py ──▶ ingest/* ─────────────────────────────────────┘
```

- `models/` has no dependencies inside the app. Start there.
- `graph/` depends only on `models/` and `config`.
- `agent/` depends on `graph/` and `models/`.
- `api/` is the only layer that knows about HTTP.
- `ingest/` reuses `agent.nodes.invoke_with_reason` for its model call. That is
  the one place ingestion reaches into the agent package, and it is deliberate:
  there must be exactly one place that knows how to call a model and interpret
  the answer.

Nothing in `graph/` or `models/` imports from `agent/`, so the data layer is
testable and demonstrable without the AI half at all.

---

## 2. The graph

### 2.1 Identity

Every node carries a stable string `id` that is its primary key across the whole
system — the API, the UI, citations in an answer, and the `CITED` edges in
memory all use it. A unique constraint per label (`graph/schema.py`) makes id
lookups index-backed and keeps duplicates out.

Ids are prefixed by kind, which is how the critic can tell a real citation from
prose in brackets: `per-`, `svc-`, `proj-`, `inc-`, `dec-`, `doc-`, `inv-`,
`doc-ingested-`.

### 2.2 Labels and relationships

**7 labels:** `Person`, `Service`, `Project`, `Incident`, `Decision`, `Document`,
`Investigation`.

**12 relationship types**, each earning its place:

| From → To | Type | What it buys |
|---|---|---|
| Person → Service | `OWNS` | Ownership, and therefore *who to ask*. Never inferred — the owners list in an answer comes from these edges or says "no owner recorded". |
| Person → Project | `WORKED_ON` | Experience. Combined with `USES` this is a two-hop answer to "who knows this system?" |
| Person → Incident | `RESOLVED` | A second route to relevant people, unioned with the project route. |
| Project → Service | `USES` | The other half of the experience join. |
| Service → Service | `DEPENDS_ON` | **Read backwards.** `(A)-[:DEPENDS_ON]->(B)` means A breaks if B breaks, so "what breaks if B changes" matches services pointing *into* B. The single most load-bearing edge in the product. |
| Incident → Service | `AFFECTED` | Which incidents are relevant to a service. |
| Incident → Service | `CAUSED_BY` | Asserted **only** where the source material supports it. Its *absence* is a first-class result. |
| Decision → Service | `AFFECTS` | "Why do we use this?" |
| Decision → Decision | `SUPERSEDES` | Turns a rationale question into an answer that includes its own replacement. |
| Document → Service/Decision/… | `DESCRIBES` | Provenance for seeded documents. |
| Document → Decision, Incident | `SUPPORTS` | Provenance for a document whose source is an ADR or a postmortem. Queried by `SUPPORTING_DOCUMENTS` alongside `DESCRIBES`; the seed uses it four times, once on a postmortem pointing at an incident. |
| Investigation → anything | `CITED` | Memory as structure. See §2.4. |

### 2.3 The seed dataset, and its deliberate holes

The fictional company is "Northwind Logistics": 10 people, 18 services, 5
projects, 6 incidents, 5 decisions, 8 documents (52 nodes, 124 relationships).

`seed/seed.py` validates before it writes: every id unique, every row carrying
the fields its label requires, and **no relationship referencing an unknown
entity**. That last check is the ground truth behind the "never invent
relationships" rule — if the dataset is unsound, nothing downstream can be
trusted. There is also a test that `DEPENDS_ON` contains no cycle, because a
cycle would make "what breaks" a question with no finite answer.

Two holes exist on purpose. Both are demo material, not oversights:

1. **`svc-payment-legacy` depends on `svc-identity`; `svc-payment-v2` does
   not**, and nothing in the graph explains the difference. The agent must
   surface this as a question, not glue over it.
2. **`inc-2026-04-webhook-latency` has no `CAUSED_BY` edge.** The agent must
   report "the cause is not recorded" rather than attribute it.

Seeding is idempotent: every node is `MERGE`d on `id`, so running the seeder
twice leaves the graph unchanged. `--reset` deletes the graph first, which also
invalidates the cached graph handle — `seed()` calls `client.reset_connection()`
afterwards for exactly that reason.

### 2.4 Memory is structure, not a log table

An investigation is a node like any other. Its citations are real edges:

```cypher
MATCH (inv:Investigation {id: $investigation_id})
UNWIND $citations AS citation
MATCH (target {id: citation.id})
MERGE (inv)-[:CITED {quote: citation.quote}]->(target)
```

That is what lets a later session *traverse* from a past answer into the
services and people it touched, rather than reading a blob of text and hoping.
`save_investigation` filters the citation list through `get_entity` first, so a
citation pointing at something that does not exist cannot pollute the graph.

Nested metadata (intent, confidence, tool-call count, critic verdict) is stored
as `metadata_json` — a JSON *string* — because FalkorDB properties must be
primitives or arrays of primitives. `get_investigation` parses it back and
tolerates a malformed value.

### 2.5 FalkorDB gotchas that cost real time

These are the ones already paid for. They will bite again.

| Gotcha | Detail |
|---|---|
| `result.result_set` is **positional** | Rows are lists of scalars; column names live separately in `result.header` as `[type_code, name]` pairs. Assuming dicts made *every* live query return garbage while the in-memory fake agreed with itself. `_result_to_dicts` is the fix. |
| No parameters inside a variable-length range | `[:DEPENDS_ON*1..$max_depth]` fails with "Encountered unhandled type in inlined properties". The bound must be a literal, which is why `queries.build()` interpolates a validated `int`. |
| Labels and relationship types cannot be parameterised | Hence the double allowlist check (§4.3). |
| No null property values | An absent property and a null one mean the same thing; `_props_for` skips nulls rather than coercing them. |
| No nested maps | Non-primitive values are stringified rather than dropped — losing a field silently is worse than storing it as text. |
| Constraint re-creation reports as an error | Re-running `apply_schema()` logs at debug and is not a failure. |
| The port is often not 6379 | FalkorDB Cloud hands you a `host:port` where the port is arbitrary, and there is no TLS on the Free tier. |

### 2.6 Schema and indexes

`apply_schema()` creates a unique constraint per label plus four full-text
indexes (`Document` title+content, `Decision` title+rationale, `Incident`
title+summary, `Service` name+description). Full-text indexes are provisioned
but the read path currently filters with `CONTAINS`; switching to full-text
search is an easy win if the graph grows.

---

## 3. The query layer

`app/graph/queries.py` is **the security boundary of the whole application**.
Every Cypher string the app can execute lives here as a module-level constant.
The model never sees, generates, or influences Cypher text — unions, subqueries
and all, there is no code path by which model output reaches a query string.
A test asserts `execute_raw_cypher` does not exist.

**29 constants:** 18 read, 6 memory, 5 ingestion.

### 3.1 Two conventions

1. **Impact traverses `DEPENDS_ON` backwards.** `min(length(p))` collapses the
   many paths to one node into a single shortest hop count.
2. **Paths are returned flat** — `nodes` and `rel_types` arrays plus a `depth`,
   rather than native path objects. `_rows_to_paths` rehydrates them. This keeps
   serialisation predictable and every hop inspectable by the UI.

### 3.2 The three helpers

| Helper | Job |
|---|---|
| `build(template, depth)` | Fills `{max_depth}`, `{nodes}`, `{rels}` in one pass. Templates are plain strings, never f-strings, so `{id: $service_id}` map literals are not mistaken for placeholders. |
| `max_depth(requested)` | Coerces to `int` and clamps to `GRAPH_MAX_DEPENDENCY_DEPTH` (default 3, ceiling 6). A non-numeric value falls back to the ceiling rather than raising, which guarantees **only an integer can reach the template**. There is an explicit test that a hostile value cannot survive this. |
| `default_limit(default, ceiling)` | Clamps to `GRAPH_MAX_RESULTS` (default 100). Whole-graph reads pass an explicit larger `ceiling`, because clamping those to 100 would silently show a truncated graph. |

### 3.3 The read queries, grouped

- **Dependency:** `DEPENDENCY_IMPACT`, `DEPENDENCY_PATHS`, `UPSTREAM_DEPENDENCIES`, `SHARED_DEPENDENCIES`.
- **People:** `SERVICE_OWNERS`, `RELEVANT_ENGINEERS` (a `UNION` of the project route and the incident route).
- **Knowledge:** `RELATED_INCIDENTS` (the `OPTIONAL MATCH` on cause is what makes absence queryable), `DECISION_HISTORY` (with the supersession join), `SUPPORTING_DOCUMENTS`.
- **Resolution:** `SERVICE_SEARCH`, `ENTITY_SEARCH`, `ENTITY_BY_ID`.
- **Exploration:** `GRAPH_OVERVIEW`, `GRAPH_EDGE_COUNTS`, `ALL_NODES`, `ALL_EDGES`, `GRAPH_NEIGHBORHOOD`, `list_entities_template`.

`SHARED_DEPENDENCIES` deserves a note: it finds infrastructure both the old and
the new service depend on. That is the *real* migration risk — something that
must serve both paths simultaneously — and it is the kind of fact a text
retriever cannot produce at all.

---

## 4. The repository

`app/graph/repository.py` exposes every graph operation as a typed, bounded
method returning domain models rather than raw rows, so provenance — node ids,
relationship types, hop counts — survives end to end.

### 4.1 One choke point

`_rows(template, params)` executes a template and normalises the result. Every
read goes through it, which means timeouts and error translation are handled in
exactly one place: any failure becomes `GraphUnavailable`, which the API renders
as a 503 through the standard envelope, never a 500 with a stack trace.

`_result_to_dicts` is the FalkorDB-shape adapter described in §2.5.

### 4.2 Notable methods

| Method | Why it is shaped this way |
|---|---|
| `impacted_services` | Also resolves owners for the changed service *and* every impacted one, so the agent does not spend two tool calls to get them. |
| `relevant_engineers` | Ranks by count of distinct engagements, then de-duplicates on `(person, project)` so the busiest reviewer surfaces first. |
| `related_incidents` | Leaves `cause_names` empty when there is no `CAUSED_BY` edge. The emptiness *is* the answer. |
| `recall_investigations` | Ranking happens in Python (`rank_investigations`), not Cypher: cheap, and auditable. Filler words are dropped via a stopword set, which is why "what is the timezone for the team" no longer matches an unrelated stored question on shared glue words. |
| `entity_catalogue` | id → name for every non-`Investigation` node. Handed to the extractor so it reuses existing ids instead of minting duplicates. |
| `list_entities` | Validates the label against `EntityType` before interpolation — this is the interlock for the one read query that must interpolate a label. |

### 4.3 The write boundary

`upsert_entities` and `upsert_relationships` group by label/type because Cypher
cannot parameterise either, then **re-check every value against
`_ENTITY_LABELS` / `_RELATION_TYPES` and raise** rather than write. This is the
second of two independent checks — the extractor validates first, the repository
validates again at the moment of writing. It is deliberate duplication: the
extractor is the boundary for *one* caller, the repository is the boundary for
*all* of them, and a future code path that bypasses the extractor is still safe.
`Investigation` is excluded from the writable label set.

---

## 5. The agent

`app/agent/` — a fixed seven-node LangGraph pipeline.

```
plan → retrieve → assemble → write → critic → finalize → memory → END
```

**It is acyclic by construction.** There are no conditional edges and no loops,
so the pipeline cannot spin. Boundedness comes from three independent places:
the acyclic topology, the toolbox's per-run call budget
(`AGENT_MAX_TOOL_CALLS`), and LangGraph's `recursion_limit`
(`AGENT_MAX_RECURSION`). Even a misbehaving node terminates.

The critic sits **after** the writer because a critic needs something to audit;
`finalize` applies its verdict before the answer is returned or stored.

### 5.1 State

`InvestigationState` is a `TypedDict` holding input, the plan, everything
retrieval found, reasoning artefacts, and output. Two entries are injected at
construction and never serialised:

- **`_toolbox`** — the per-run `GraphToolbox`. Carried in state rather than a
  global so concurrent investigations each get their own budget.
- **`_progress`** — an optional callback invoked with each `ExecutionStep` as it
  happens, so an async caller can show progress instead of waiting.

One field has a reducer:

```python
steps: Annotated[list[ExecutionStep], operator.add]
```

Without it LangGraph **replaces** the list on every node and only the final
node's steps survive. That was one of the nine defects the test suite caught;
the comment in `state.py` exists to stop someone "simplifying" it away.

### 5.2 The nodes

| Node | Reads | Writes | Notes |
|---|---|---|---|
| `plan` | question, full service catalogue | `plan`, `resolved_subject`, `resolved_comparison` | Classifies intent, extracts the two service names. |
| `retrieve` | plan, resolved services | `impacted`, `paths`, `owners`, `engineers`, `incidents`, `decisions`, `documents`, `shared_dependencies`, `upstream`, `evidence`, `recalled` | Runs only the tools the intent implies. |
| `assemble` | everything above | `evidence`, `missing_evidence` | Normalises, de-duplicates, and *names the gaps*. |
| `write` | evidence, paths, gaps | `answer`, `confidence`, `cited_ids`, `recommendations` | Model draft, or deterministic fallback. |
| `critic` | draft answer + rendered evidence | `critique` | Deterministic citation audit, then model reasoning. |
| `finalize` | critique, answer | `answer`, `steps` | A `qualify` verdict appends a Verification-notes section. |
| `memory` | citations, answer | `status`, `cited_ids` | Persists node + `CITED` edges; a failure is logged and stepped, never fatal. |

**Planning is rules-first, model-second, and rules win.**
`_merge_plan` runs a keyword intent classifier and a set of regex pair patterns
("replace X with Y", "swap X for Y", "use Y instead of X", …), then lets the
model *improve* the answer only where the rules found nothing. A hallucinated
service name can therefore never override a grounded match. `match_services`
uses longest-alias-wins so "Payment Service" cannot shadow "Payment Service A",
and `snap_to_service` strips articles and trailing clauses ("the checkout api",
"payment service a for checkout") onto the closest real alias — those fragments
would match nothing because the graph search is a plain `CONTAINS`.

**Retrieval is intent-routed.** Spending budget on incident history for an
ownership question is waste:

| Intent | impact | ownership | engineers | incidents | decisions |
|---|---|---|---|---|---|
| `replacement` | ✅ | ✅ | ✅ | ✅ | ✅ |
| `impact` | ✅ | ✅ | ✅ | ✅ | — |
| `ownership` | — | ✅ | ✅ | — | — |
| `incident` | ✅ | ✅ | — | ✅ | — |
| `rationale` | — | ✅ | — | — | ✅ |
| `explore` | ✅ | ✅ | ✅ | ✅ | ✅ |

The subject service is always added to `scope_ids` even when impact analysis is
skipped. Without that, an ownership or incident question would query an empty
service list and find nothing — defect #3 in the `CHECKLIST.md` table.

`recall_investigations` always runs, before anything else, so a follow-up
question can see what was concluded last time.

**Every tool call is recorded, including the ones that do not happen.**
`_safe_tool` turns a budget-exhausted or invalid call into a visible `skipped` /
`failed` step rather than an exception, so the UI shows the agent was *bounded*
rather than broken.

**The critic audits in two passes.** First, a deterministic regex: every `[id]`
in the draft must exist in `_known_ids(state)`. Then the model reasons about
semantics a regex cannot see. The two findings are **unioned**, never replaced —
the model must not be able to drop the deterministic catch. `_known_ids` must be
*complete*: an id missing from the whitelist produces a false "unsupported
claim" on a perfectly grounded answer, and a critic that cries wolf is worse
than no critic. The docstring records the bug where the subject service and
project ids were omitted.

**The writer has a deterministic fallback** (`_deterministic_answer`) that
composes the same structure from graph evidence. It is what makes
`LLM_ENABLED=false` a supported mode rather than a broken one, and it is the
safety net that guarantees the API always returns something evidence-backed
instead of an error page. `write_node` says which writer produced the answer in
the step detail and sets `confidence` from whether every cited id was actually
retrieved.

**Recommendations are derived from structure only** (`build_recommendations`):
reviewers come from `OWNS` and `WORKED_ON` edges, the migration checklist comes
from documented gaps. Each recommendation names the evidence ids backing it, and
every one carries `requires_human_approval=True`. Nothing is executed.

### 5.3 The toolbox

`GraphToolbox` is the *only* bridge between the model and the database. Ten
allowlisted tools; anything else is rejected before it reaches the repository.

```
resolve_entity · dependency_impact · owners_of · relevant_engineers
related_incidents · decision_history · supporting_documents
shared_dependencies · upstream_dependencies · recall_investigations
```

Each returns a `ToolResult` of three things: `data` for the pipeline, an
`Evidence` record for the answer, and a `step` for the UI. **Nothing reaches the
writer without being attributable.** `_consume()` enforces the allowlist and the
budget; once the budget is spent, tools refuse rather than letting a confused
agent loop.

`_unique()` is order-preserving de-duplication of `source_ids`. Graph queries
that traverse a join return the same id more than once — that is meaningful for
the rows, but React needs unique keys for the chips.

---

## 6. LLM wiring

`app/llm.py` resolves a provider lazily and caches the client.

| `LLM_PROVIDER` | Behaviour |
|---|---|
| `nvidia` (default in `.env.example`) | NVIDIA NIM via `ChatOpenAI` — NIM is natively OpenAI-compatible, so this is its real interface, not an adaptation. Requires `NVIDIA_API_KEY` or resolves to `None`. |
| `google` | Gemini via `langchain-google-genai`, the official client. Not the OpenAI-shaped shim: Gemini-specific behaviour is the real thing. Requires `GOOGLE_API_KEY`. |
| `auto` | Whichever key exists, NIM first. |

Naming a provider whose key is missing resolves to `None` rather than silently
falling back, so a typo cannot quietly spend the other account's quota.

`LLM_ENABLED=false`, a missing key, or an unreachable provider all raise
`LLMUnavailable` — caught at every node, never at import — so the API can return
a clean 503 and the agent can fall back to its deterministic writer.

`get_llm()` is `lru_cache`d; `reset_llm_cache()` exists for tests that patch
configuration.

### 6.1 The three-valued call

`agent/nodes.py` has one function that talks to a model:

```python
invoke_with_reason(system, user, timeout) -> tuple[str, str | None]
```

| Returns | Meaning |
|---|---|
| `("<text>", None)` | The model answered. |
| `("", None)` | **No model is configured.** Nothing was attempted, so there is nothing to report. This is the honest "no model available". |
| `("", "<reason>")` | A call **was attempted and failed**. Exhausted key, rejected model id, and timeout all land here. |

The distinction exists because the extractor used to collapse the last two into
one. A failed call was reported as "No model was available", sending the reader
to their configuration for a problem that was not there. `_invoke` remains as a
thin wrapper for callers that only want the text.

**`timeout` is accepted but not honoured.** The effective bound is the client's
(`AGENT_QUERY_TIMEOUT_SECONDS × 4` with `max_retries=2`), so a dead provider
costs roughly three minutes before this returns. This is documented in the
docstring and open in `SESSION_DUMP.md`; it is the code-side fix for §7 of the
handoff.

### 6.2 Where the fallbacks live

| Node | Fallback when the model gives nothing |
|---|---|
| `plan` | Heuristic intent classifier + regex pair patterns + local name matching. |
| `write` | `_deterministic_answer` — a full structured answer from evidence. |
| `critic` | The deterministic citation audit still runs; only the semantic pass is skipped. |
| ingestion | The document is stored and citable; the report says the call failed, with the reason. |

---

## 7. Document ingestion

Uploading a document is how the graph grows beyond the seed. The order is the
whole point:

```
1. convert   the file → Markdown, locally, free
2. extract   model proposes entities/relationships → validated
3. write     document → new entities → relationships → provenance edges
```

Both entry points — a file and pasted text — run the identical pipeline. The
paste path simply skips conversion. The UI offers whichever suits the user
without a second code path.

### 7.1 Conversion (`ingest/documents.py`)

Microsoft **MarkItDown** is the single conversion step, so the extractor only
ever sees one shape of input: a PDF, a Word file and a pasted runbook take
exactly the same path. Conversion is local and costs nothing.

Guards, in order:

| Guard | Behaviour |
|---|---|
| Empty upload | `UnsupportedDocument("The uploaded file is empty.")` |
| > `MAX_UPLOAD_BYTES` (8 MB) | Refused. The route refuses at `file.size` **before reading the body**, so an oversized upload is not pulled into memory first (413, `payload_too_large`). |
| Unsupported extension | 15 extensions accepted; the message names them. |
| Conversion fails | The MarkItDown error is surfaced verbatim — upload failures are normal, not bugs. |
| Converts to no text | Told to OCR a scan rather than silently ingesting nothing. |
| > `MAX_EXTRACT_CHARS` (60 000) | Truncated **on a paragraph boundary** so the model does not receive half a sentence and invent the rest. |

### 7.2 Extraction (`ingest/extract.py`)

This is where the AI is, and the validation is the important half. A model asked
for graph data will happily invent a label that does not exist, point a
relationship at a stranger, or mint a plausible id for something real. All three
are refused **with a reason**, and everything refused is reported — nothing is
dropped silently, because a misread document and a broken extractor otherwise
look identical.

`validate_extraction(payload, known_ids)` is pure and deterministic: no model,
no database. That is deliberate — it is the security boundary and it should be
cheap to test exhaustively.

| Rule | Rejected when |
|---|---|
| Label allowlist | `type` is not one of the 6 extractable labels. `Investigation` is deliberately absent: it is the agent's own record of a question, not something a document describes. |
| Relationship allowlist | `type` is not a `RelationType`. |
| Usable id | id and name are both empty after slugifying. |
| Duplicates | Same id twice in one response — the first wins, silently (not an error worth shouting about). |
| Endpoints exist | `from_id`/`to_id` is neither an entity in this document **nor** an id already in the graph. **This is the mechanism that keeps "never invent relationships" true with a model in the loop.** |
| No self-links | `from_id == to_id`. |
| Caps | > 40 entities or > 60 relationships. |

The prompt (`EXTRACTOR_SYSTEM`) states the same nine rules, then `validate_extraction`
enforces them — because a model that *agrees* to the rules is not the same as a
model that *follows* them. Note that the prompt says "an empty list is a valid
answer": we would rather have fewer, better-supported facts.

The extractor takes an `invoke=` seam, which scripts a *successful* answer and is
what the ingestion tests use. `_call_model` is the real tuple-returning call,
isolated so the **failure** path can be driven without a provider. Two seams,
because success and failure need different tests.

### 7.3 Writing (`ingest/service.py`)

Two rules shape the write, and both exist to protect curated data from a
misreading:

1. **Existing entities are never overwritten.** An id already in the graph is
   *linked*, not restated. The worst a bad extraction can do is add a visible,
   reversible link.
2. **The document always gets provenance.** `DESCRIBES` edges are derived from
   the document's **own entity list**, not from what the model proposed for
   relationships. A document therefore stays reachable from the things it talks
   about even if the extractor returned nothing at all.

The document id is **content-derived**:

```python
sha256(f"{title}\n{markdown}")[:12]  →  "doc-ingested-<digest>"
```

Re-uploading the same document updates one node instead of accumulating
near-duplicates, and the id is reproducible across processes — unlike a uuid,
which would create a new document on every retry. The consequence to remember:
**editing a document and re-uploading creates a new node**, because the content
changed. Correcting a typo in the title does the same.

The report splits `entities_created` from `entities_linked` on purpose: "the
graph learned something new" and "the graph already knew this" are different
outcomes, and collapsing them would overstate what the document contributed.

### 7.4 Progress and reporting

Phases are published as each one **finishes**, as an `IngestStep(phase, title,
detail, duration_ms)` through an `on_progress` callable (default `None`). The
phase titles change with what happened, which is the point:

| Situation | `extract` step says |
|---|---|
| Model worked | "Read the document for entities — 4 entities, 3 relationships, 1 refused" |
| Call attempted, failed | **"The model call failed"** + the reason + "the document is still stored and citable" |
| No model configured | "No model available — nothing extracted; the document is still stored and citable" |

`GET /api/ingest/capabilities` tells the UI whether a model is available
*before* an upload, so the user is warned up front rather than surprised in the
result.

---

## 8. The async job pattern

Both investigations and ingestion are **queued, not held open**. The same shape
appears twice:

```
POST  → 202 {id, poll_url}
        background thread runs the work
GET /{id}/status → steps so far; when done, the result
?wait=true       → block and return the whole payload
```

### 8.1 Why two registries, not one generic one

`app/agent/jobs.py` and `app/ingest/jobs.py` are separate, and this is
**deliberate duplication of roughly 50 lines**. The two jobs carry different
payloads and their status shapes are published API, so folding them together
would mean renaming the investigation fields that already work. The docstring in
`ingest/jobs.py` says exactly this, so the next person does not "helpfully"
merge them.

### 8.2 What the pattern buys

- **The work is genuinely slow.** One run makes graph round trips plus two or
  three model calls. Holding an HTTP connection open for it is fragile: proxies
  time out and the browser shows one spinner with no progress.
- **Progress is observable.** `run_job` passes a `publish` callback into
  `run_investigation`, so steps accumulate as they happen. In ingestion the
  callback is a lambda straight into `registry.append_step`.
- **Nothing blocks the event loop.** The pipelines are synchronous, so they go
  through `run_in_threadpool` when waiting and through Starlette's background
  task pool when queued. **This was a real bug**: the ingestion route used to be
  `async def` and run the pipeline inline, freezing every other request in the
  process for the length of a model call — measured at 18.2s for `/health`
  during one upload, versus 0.03s after the fix. The regression test asserts
  *latency*, not the presence of a threadpool call (and its first version passed
  against the bug, because it timed `/health` after the blocking call had
  already finished; it watches timer accuracy now).

### 8.3 Failure semantics

- **Registry state is in-process.** A restart loses in-flight jobs. That is the
  honest outcome — an absent job reads as absent rather than as a phantom
  "running" forever. FastAPI workers each keep their own registry, so the same
  applies to multiple workers.
- **A job never raises into the worker.** `run_job` and `run_ingest_job` catch
  everything and record it, because the client is polling either way.
- **A finished investigation survives a restart** in a limited but useful way:
  `GET /api/investigations/{id}/status` falls back to the *persisted graph
  record* when no live job exists, returning the stored answer with
  `done: true`. Ingestion has no such fallback — a lost ingest job is a 404.
- **`append_step` exists as its own method** because `get` takes the same
  non-reentrant lock; publishing from inside a `get` would deadlock. There is a
  comment about this in both registries.

---

## 9. The API surface

13 documented routes, one error envelope for every failure:

```json
{"error": {"code": "…", "message": "…", "detail": "…"}}
```

| Method | Path | Purpose | Notable |
|---|---|---|---|
| GET | `/health` | Process + graph + LLM reachability | **Never raises.** An unreachable graph yields `degraded` with HTTP 200, so a container orchestrator does not kill a pod that is merely waiting on credentials. |
| GET | `/api/graph/overview` | Counts per label and relationship | Used by the dashboard header and as a seeding check. |
| GET | `/api/graph/full` | Every node and edge | Edge endpoints that do not resolve to a returned node are dropped, so the renderer never guards against dangling references. |
| GET | `/api/graph/entities` | Every entity of one label | Validates the label; backs the data browser. |
| GET | `/api/graph/neighborhood` | Subgraph around an entity | An unknown id returns an **empty subgraph**, not a 404, so the UI can render "not found in graph" without special-casing. |
| POST | `/api/investigations` | Start an investigation | 202 + poll URL, or 200 with `?wait=true`. |
| GET | `/api/investigations/{id}/status` | Poll an in-flight job | Falls back to the stored record after a restart. |
| GET | `/api/investigations/history` | Past investigations | Declared **before** `/{id}` so FastAPI matches the literal path first. |
| GET | `/api/investigations/{id}` | One stored investigation | Includes the entities it cited. |
| GET | `/api/ingest/capabilities` | Extensions, size limit, source types, `model_available` | Lets the UI warn before an upload. |
| POST | `/api/ingest/text` | Ingest pasted text | 202 by default, or the report with `?wait=true`. |
| POST | `/api/ingest/file` | Ingest an upload | 413 before reading the body when oversized. |
| GET | `/api/ingest/{job_id}/status` | Ingestion progress | A missing job is a 404 — a lost job and a job that never started are different problems. |

Plus `GET /` (not in the schema) which points humans at `/docs`.

Status mapping lives in `api/errors.py`: 4xx for the caller's fault, 503 for a
dependency that is not ready (`GraphUnavailable`, `LLMUnavailable`), 500 for the
unexpected. `_CODE_BY_STATUS` is the single lookup table — 413 was missing from
it at one point, which would have surfaced an oversized upload as a bare
`http_error`.

**Route ordering matters.** `/history` is declared before `/{investigation_id}`
in `investigations.py` for a reason that is easy to undo.

---

## 10. The frontend

Next.js 16 · React 19 · Tailwind 4 · TypeScript. No component library, no chart
library, no graph library.

### 10.1 Layout of the dashboard

`app/page.tsx` is written as an **assessment document, not a dashboard**:
masthead → question → two-column report (answer + supporting logs on the left,
graph and reasoning trace on the right) → full-width evidence beneath, because
evidence is the most reference-like material.

**Selection is one piece of shared state.** Clicking a citation in the answer, a
chip in the evidence panel, a row in the blast radius, or a node in the graph
all focus the same entity id. That is what makes a claim traceable in one click,
and it is the reason the components talk to `highlightedId` rather than to each
other.

### 10.2 The run-token pattern

`activeRun` is a `useRef<symbol>` that identifies the current run. Every poll
loop checks it before applying state, so:

- a stale loop cannot keep issuing requests or update state after a new run
  started, and
- unmounting abandons the loop (the cleanup sets `activeRun.current = null`).

The ingest panel uses the same pattern with a `DEADLINE_MS` of 15 minutes.

### 10.3 Theme

The theme lives on `<html data-theme>` and is set by a tiny inline script in
`layout.tsx` before first paint, so a dark-theme user never sees a white flash.
Because it lives on the document element rather than in React, it is read with
`useSyncExternalStore` — no effect-mirroring, and no hydration mismatch on the
toggle label. `suppressHydrationWarning` on `<html>` is there for the same
reason.

### 10.4 The API client

`lib/api.ts` is the only place that knows the base URL. `request<T>` normalises
everything into `ApiRequestError` with a user-safe message: HTTP errors are read
out of the error envelope, network failures become a message that names the base
URL and mentions `CORS_ORIGINS`, and an aborted request becomes a timeout rather
than a raw `TypeError`. A `FormData` body is left alone — forcing JSON would make
the upload unparseable on the server.

Every response shape is mirrored in `lib/types.ts`.

### 10.5 The graph views

- **`/` (dashboard)** uses `api.neighborhood` plus the evidence bundle to draw a
  focused, path-highlighted canvas.
- **`/graph`** is the data browser. **Graph** view draws the whole graph from
  `/api/graph/full`; **Table** view lists entities per label with full
  properties from `/api/graph/entities`. That is the "show me what you actually
  know" view — a reader can check the dataset's scope and quality without
  writing a query.

`lib/force.ts` is a hand-rolled force layout: `computeLayout` returns
positions, and it also owns node colours, radii and label truncation.
`components/GraphCanvas.tsx` owns the interaction — SVG `viewBox` zoom/pan, node
dragging, and a **native** (non-React) `wheel` listener, because React attaches
`wheel` passively and the page used to scroll while the graph zoomed. There is
**no plotting dependency**, which keeps the runtime tree to three packages
(`next`, `react`, `react-dom`) and means the layout is ours to explain.

### 10.6 Design tokens

Colours come from tokens in `globals.css`: `page`, `page-raised`, `ink`,
`ink-soft`, `ink-faint`, `rule`, `rule-soft`, `plate*`, `signal`,
`signal-wash`, `verify`, `verify-wash`, `link`, `link-soft`. There is **no
`warn` and no `link-wash`** — reaching for one that does not exist is a silent
invisible element. Fonts: Spectral for answer prose (it is read, not scanned),
IBM Plex Sans for the interface, IBM Plex Mono for real identifiers only.

### 10.7 React 19 lint strictness

Next 16 + React 19 lint will fail a build for things an older setup tolerated:

- `react-hooks/refs` forbids writing a ref during render.
- Callbacks passed to components must be plain functions (wrap in `useCallback`).
- The `next dev` process **rewrites `frontend/AGENTS.md`** with its own
  agent-rules block. Removing it from a diff only re-creates the uncommitted
  change; committing it with your work is what keeps the tree clean.

---

## 11. Testing

218 tests, 1 skipped. **No test ever calls a model, and no test needs a
database.** Both are deliberate.

### 11.1 The fake repository

`tests/conftest.py` builds `FakeGraphRepository` from the *same* seed data and
reproduces the Cypher semantics in Python — including the reverse `DEPENDS_ON`
traversal and the ranking rules (shared with production code via
`rank_investigations`). The whole agent pipeline therefore runs
deterministically and for free. An autouse fixture forces `LLM_ENABLED=false`.

Shared with production code, never reimplemented:

- `rank_investigations` — ranking rules
- `dedupe_paths` (mirrored)
- the seed dataset itself

### 11.2 The integration marker

```bash
uv run pytest -m integration
```

`TestLiveFalkorDB` in `tests/test_queries.py` runs the same assertions against a
real instance. This is the part that earns its keep: the fake agreed with itself
while the live driver disagreed (positional rows, parameters in variable-length
ranges). Only a live run surfaces that class of bug.

The live-dataset test asserts *"nothing from the seed is missing"* rather than
exact equality, because ingestion is a feature that adds to the graph.
Similarly, the investigation-memory test scans recent investigations for one
with citations instead of assuming the newest has them — a citation-free
investigation is legitimate, which is what you get with no model configured.

### 11.3 Module map

| File | Covers |
|---|---|
| `test_queries.py` | Dataset integrity (ids, no cycles, dangling refs), depth/limit clamping, template building, **the injection test**, and the live suite. |
| `test_agent.py` | `invoke_with_reason`, entity resolution, planner, JSON extraction, tool bounds, evidence grounding, the full pipeline, persistent memory, recommendations, evidence normalisation. |
| `test_api.py` | Health, graph endpoints, investigations, validation, memory endpoints, the error envelope, async investigations, the job registry, live progress, provider selection. |
| `test_ingest.py` | Conversion, extraction validation, extraction wiring, `ingest_document`, the schema interlock, the ingest API, the job registry, and **`TestIngestDoesNotBlockTheServer`**. |

### 11.4 The two tests worth understanding before you touch them

1. **`test_depth_slot_cannot_be_used_for_injection`** — asserts a hostile
   `depth` value cannot survive into the query string. It is the test that makes
   the one literal interpolation defensible.
2. **`TestIngestDoesNotBlockTheServer`** — asserts *timer accuracy* under
   concurrency in both the waiting and the queued path. Reverting the
   `run_in_threadpool` fix fails it with "the event loop stalled for 1.56s".

Nine defects caught by this approach are catalogued at the end of
`CHECKLIST.md`. Defect #7 (positional rows) is the argument for the whole
design.

### 11.5 Verified numbers

```
18.2s → 0.03s   /health latency during an upload, before and after the threadpool fix
0.10s           POST /api/ingest/file (queued)
t+1s            "convert" step visible while the model was still working
12.15s          ?wait=true, blocking, returning the full report
218 passed, 1 skipped
```

---

## 12. Decision log

Answers to "why is it like this?" — including the alternatives that were
rejected. These are the decisions a PR is most likely to accidentally undo.

### D1 — FalkorDB as the context layer

**Context.** Company knowledge is relational; retrieval over text returns
isolated snippets.

**Decision.** FalkorDB, used for four specific jobs: multi-hop impact traversal,
provenance as first-class structure, supersession chains, and structured
absence.

**Alternative rejected.** Postgres with recursive CTEs — workable, but the
product's whole pitch is graph-shaped, and "structured absence" is far easier to
express.

**Consequence.** Free-tier hosting is a live dependency and the port is not
6379. TLS is off on Free.

### D2 — The model selects tools; it never writes Cypher

**Context.** An agent with a database connection is an agent that can run
`MATCH (n) DETACH DELETE n`.

**Decision.** Ten allowlisted tools; every query is a module-level constant;
values travel in `params`. Bounded traversal and result sizes.

**Consequence.** Adding a capability means adding a tool and a template, not
just prompting harder. That friction is the feature. A test asserts
`execute_raw_cypher` does not exist, and `_consume()` rejects any tool name not
in the allowlist.

### D3 — A fixed acyclic pipeline, not a ReAct loop

**Context.** ReAct-style loops are easy to write and hard to bound; they can
spin, and their cost is unbounded.

**Decision.** Seven nodes, no conditional edges, no loops. Boundedness from
three independent places (topology, tool budget, recursion limit).

**Alternative rejected.** A self-directed loop with a step cap — the cap would
have been the *only* bound.

**Consequence.** Real added capabilities need a node or a tool, and the order of
nodes is a design decision (`write` before `critic`, `finalize` after `critic`).

### D4 — Every LLM node has a deterministic fallback

**Context.** A hackathon demo cannot depend on a metered endpoint being
reachable, and tests must not spend quota.

**Decision.** `LLM_ENABLED=false` is a real, supported setting that runs the
whole app. The writer composes a full structured answer directly from graph
evidence; the planner falls back to rules; the critic keeps its deterministic
audit.

**Consequence.** 218 tests run free and offline. The app is demonstrable with no
key at all. The cost is that two answer paths must be kept in sync in spirit.

### D5 — Citations as graph edges, not a log table

**Context.** "Remember previous investigations" is easy to fake with a table of
text.

**Decision.** `(Investigation)-[:CITED]->(entity)`. Nested metadata is stored as
`metadata_json` because FalkorDB takes primitives only.

**Consequence.** A later session can *traverse* from a past answer into what it
touched. Ranking of past investigations happens in Python for auditability.

### D6 — Two job registries rather than one generic one

**Decision.** `agent/jobs.py` and `ingest/jobs.py` stay separate, duplicating
~50 lines.

**Rejected.** A generic registry parameterised over payload and status shape —
would have meant renaming the investigation status fields that were already
published API.

**Consequence.** Two small parallel files. The duplication is documented in the
module docstring so it survives review.

### D7 — 202 + poll for anything slow, and never on the event loop

**Context.** Uploads used to freeze the entire API for the length of a model
call (18.2s measured; ~3 minutes once the real provider's retries are counted).

**Decision.** Investigate and ingest are queued; the synchronous pipelines run
in a worker thread in both the queued and the `?wait=true` path; phases are
published as they finish.

**Consequence.** Registry state is in-process, so a restart loses in-flight
jobs — accepted as the honest failure. A latency regression test guards the
threadpool decision.

### D8 — Ingestion validates against allowlists and never overwrites

**Decision.** `validate_extraction` is pure and refusable; unknown labels, known
types and unresolvable endpoints are rejected with reasons; existing entities
are linked, never restated; provenance comes from the document's own entity
list.

**Consequence.** A bad extraction cannot corrupt curated data — the worst it can
do is add a visible link. Rejected proposals are reported, never dropped.

### D9 — MarkItDown as the single conversion step

**Decision.** Everything becomes Markdown first, then one extractor.

**Alternative rejected.** Per-format extractors — more code paths, more places
for an `UploadFile` to be mishandled.

**Consequence.** Non-text PDFs need OCR before upload; the error says so.

### D10 — Content-derived document ids

**Decision.** `sha256(title + markdown)[:12]`.

**Alternative rejected.** Uuid per upload — every retry creates a new document.

**Consequence.** Re-uploading the same content updates one node. Editing content
creates a new node.

### D11 — A provider abstraction with a real Gemini client

**Decision.** `LLM_PROVIDER=nvidia|google|auto`; NIM through `ChatOpenAI`
because NIM *is* OpenAI-compatible; Gemini through the official
`langchain-google-genai` client.

**Rejected.** Driving Gemini through the OpenAI-compatibility shim — the
owner was explicit that it should be a real Gemini client.

**Consequence.** Two client builders, and `google_model` /
`nvidia_model` are separate settings.

### D12 — Three-valued model-call outcome

**Decision.** `invoke_with_reason` separates "answered", "no model configured",
and "attempted and failed, here is why".

**Context.** Collapsing the last two meant a slow model was reported as a
missing key — while `/capabilities` simultaneously reported the model as
available. The contradiction was the biggest obstacle to trusting the demo.

**Consequence.** The reason travels as `ExtractionOutcome.model_error` →
`IngestReport.model_error` and changes what the pipeline *says*. A failed reader
is not a failed ingest: the document is still stored and citable.

### D13 — An in-memory fake plus integration tests

**Decision.** Reproduce the Cypher semantics in Python from the same seed data,
and run the same assertions live under `-m integration`.

**Consequence.** The fake makes the suite fast and free; the live suite is what
proves the fake is not lying. Defect #7 is the receipt.

### D14 — No graph or chart dependency in the frontend

**Decision.** Hand-rolled force layout in SVG.

**Consequence.** Three runtime packages in total; zoom/pan/drag are ours to
explain and fix. The trade is that the layout is our problem.

---

## 13. Recipes

### Add a graph tool (e.g. "which projects use this service")

1. Add the Cypher to `queries.py` as a module constant with `$params`.
2. Add a typed method to `GraphRepository` that calls `_rows(...)` and maps rows
   to domain models.
3. Add a method to `GraphToolbox` that consumes budget and returns
   `ToolResult(data, evidence, step)`, then add its name to `ALLOWED_TOOLS`.
4. Call it from `retrieve_node` under the right intent flags, and add it to
   `updates`.
5. If it should be citable, make sure its ids land in `_known_ids` — otherwise
   the critic will flag a grounded answer.
6. Add tests: one for the repository method against the fake, and the assertion
   in the live suite if it is shape-sensitive.

### Add a query only

Add the constant, use `queries.build(template, depth)` if it has a traversal
bound (never interpolate a raw value), and pass every other value through
`params`.

### Add an entity label or relationship type

Touch all six of these or something will silently under-report:

1. `models/graph.py` — `EntityType` / `RelationType`.
2. `graph/schema.py` — the unique constraint (labels only).
3. `seed/data.py` (+ the `label_required` map in `seed/seed.py`) if it is seeded.
4. `ingest/extract.py` — `EXTRACTABLE_LABELS` if a document may create it.
5. `frontend/lib/types.ts` if the UI needs to render it.
6. The relationship table in `README.md` and §2.2 here.

`repository._ENTITY_LABELS` / `_RELATION_TYPES` derive from the enums, so those
update themselves.

### Change a prompt

`agent/prompts.py` only. The prompts are blunt on purpose — the writer is told
an unsupported claim is worse than an admitted gap. If you relax a rule, add the
matching deterministic check in `critic_node`, because the prompt is a request
and the critic is the enforcement.

### Add an API route

Put it in `api/routes/`, depend on `get_repository` for graph access, raise
`HTTPException` for caller errors — `api/errors.py` turns it into the standard
envelope. If it can be slow, make it a job (§8) rather than holding the
connection.

### Switch the model provider

Set `LLM_PROVIDER` and the matching key in `.env`. Nothing else changes.
`reset_llm_cache()` exists for tests that patch config mid-process.

### Point at a different graph

Change `FALKORDB_*` and `FALKORDB_GRAPH`, then `uv run python -m app.seed.seed --reset`.
If a client handle is already cached, `reset_connection()` is what re-selects.

### Wipe investigation memory

`GraphRepository.clear_investigations()` — dev/test utility. It deletes only
`Investigation` nodes, so it is safe against the seeded company.

---

## 14. Debugging playbook

| Symptom | Most likely cause | First thing to check |
|---|---|---|
| Dashboard says it cannot reach the API | Wrong origin (`127.0.0.1` vs `localhost`) or the backend is on another port | `CORS_ORIGINS` in `.env`; `NEXT_PUBLIC_API_BASE_URL` in `frontend/.env.local` |
| `/health` is `degraded` | Graph unreachable — usually the port or the password | `missing_settings` in the response; then `FALKORDB_PORT` (it is often not 6379) |
| Every live query returns garbage | Someone "simplified" `_result_to_dicts` | `result.result_set` is positional, `header` holds the names |
| Impact analysis silently returns nothing | Depth interpolation collided with `str.format`, or the fake and the live query diverged | `queries.build()`; run `pytest -m integration` |
| A grounded answer gets flagged as unsupported | `_known_ids` is missing a source of ids | Add the id source, then re-run the grounding tests |
| Steps show only the last node's | The `operator.add` reducer was removed from `steps` | `state.py` — LangGraph replaces lists per node without it |
| The whole API freezes during an upload | Something blocking crept back onto the event loop | `TestIngestDoesNotBlockTheServer` |
| Upload extracts nothing, says "No model available" | Should now be impossible — a failed call reports its reason | If you see it, `invoke_with_reason` was bypassed |
| Upload extracts nothing, says "The model call failed" | The model is too slow for the client timeout | `.env`'s model; see HANDOFF §7 |
| The backend dies with no log line | It was on port 8000 and the harness reclaimed it | Move to another port |
| `next dev` died mid-request | `npm run build` ran in the same directory | Stop the dev server before building |
| A new colour token renders nothing | The token does not exist | Use the list in §10.6 |
| An edited document created a second node | Document ids are content-derived | Expected; delete the stale node or reuse the same content |
| A job is 404 after a restart | Registry state is in-process | By design; re-run it |

---

## 15. Where the remaining work is

Handoff §9 has the ordered list. In short: unblock the model, take screenshots,
deploy, record the demo, write the DEV post, triage the npm advisories, and have
someone follow the README cold on a second machine.

The other open code item is making `_invoke` honour its `timeout`, which would
turn a three-minute failure into a ten-second one. Write the stalling-stub test
first; there is a note about exactly that in `SESSION_DUMP.md`.
