# Developer handoff — OrgMemory

For whoever picks this up next. Read this first; the deep mechanics, the *why*
behind each design and the recipes for extending things live in
[`KNOWLEDGE-TRANSFER.md`](./KNOWLEDGE-TRANSFER.md).

Everything here describes the code as it is, including the parts that are
unfinished. Where the older documents (README, SPEC) disagree with the code, the
code wins — see [Documentation drift](#8-documentation-drift-known) for the
specific places they are stale.

---

## 1. What this is

**OrgMemory** is an AI "Company Brain": an engineer asks a question about their
organisation, an agent traverses a [FalkorDB](https://falkordb.com) knowledge
graph, and the answer comes back with the graph records behind every material
claim.

The problem it solves is that company knowledge is *relational*. "Can we replace
Payment Service A with Payment Service B?" is not answered by the most similar
paragraph in a runbook; it needs who depends on it, who owns those, what broke
before, and which decision put us here. Retrieval-over-text finds snippets.
A graph answers the joins.

Three things make it more than a chat wrapper:

1. **The model never writes Cypher.** It picks from ten registered tools and
   supplies arguments. Every query is a module-level constant with values in
   FalkorDB's `params` dict.
2. **Citations are graph structure, not a log line.** An answer's evidence is
   stored as `(Investigation)-[:CITED]->(…)` edges, so a later session can
   *traverse* from a past answer into the services and people it touched.
3. **It says what it does not know.** A missing `CAUSED_BY` edge is a queryable
   result — "we don't know why this happened" — and an unsupported claim in a
   draft answer is caught by a critic before the user sees it.

Built for the Graph Hacks hackathon, track 03 — Company Brain.

---

## 2. Status at a glance

### Working, tested, verified against a live database

| Area | State |
|---|---|
| Graph schema + seed | 7 labels, 12 relationship types, 52 nodes / 124 relationships, repeatable `MERGE` seeding |
| Query layer | 29 Cypher strings, all parameterised; the read path is exercised against live FalkorDB in tests |
| FastAPI | 13 documented routes; one error envelope for every failure |
| LangGraph pipeline | `plan → retrieve → assemble → write → critic → finalize → memory`, acyclic by construction |
| Persistent memory | Investigations and their citations stored in the graph, survives restart |
| Document ingestion | Upload or paste → MarkItDown → validated LLM extraction → graph write |
| Async work | Investigations *and* ingestion are queued (202 + poll), with live per-phase progress |
| Frontend | Dashboard, graph browser (`/graph`, Graph + Table views), upload panel, light/dark, mobile |
| Tests | 218 passing, 1 skipped; ruff, `tsc`, `eslint` and `next build` all clean |

### Not done

| Gap | Notes |
|---|---|
| **The model call fails** | The demo's configured NIM model is a 550B model that does not answer inside the client timeout. Extraction reports the failure honestly now, but extracts nothing. This is the single biggest obstacle to a convincing demo — see [§7](#7-the-one-thing-that-can-spoil-the-demo). |
| **`_invoke`'s `timeout` argument is inert** | `invoke_with_reason` accepts it and ignores it. The real bound is the client's (`AGENT_QUERY_TIMEOUT_SECONDS × 4`, `max_retries=2` → ~3 min per call). |
| Investigations inherit the same silence | `plan_node` uses `_invoke`, so a failed model call there degrades to "no evidence found" with no reason. The mechanism to fix it exists (`invoke_with_reason`); nobody has wired it up on that path. |
| No deployment | Both halves build; nothing is hosted. So no public demo link. |
| No demo video, no DEV blog post | Both are submission deliverables. |
| No screenshots of the redesigned UI | The old captures predate the redesign and were deleted rather than shipped stale. |
| 5 high-severity npm advisories | In the Next.js tree. `npm audit fix --force` was deliberately not run — it applies breaking changes. Untriaged. |
| Setup untested on a second machine | Verified on macOS, Python 3.12, Node 24. Nobody has followed the README cold. |
| No auth, no multi-tenancy | Out of scope for the hackathon; do not deploy this publicly as-is. |

---

## 3. Get it running

Prerequisites: **Python 3.12**, **Node 20.9+**, and a free
[FalkorDB Cloud](https://app.falkordb.cloud) instance. No Docker.

```bash
cp .env.example .env        # then fill in the values from §3.1
```

### 3.1 Configure `.env`

Two things are required — a graph and a model:

```ini
FALKORDB_HOST=instance-xxxxx.your-region.aws.example
FALKORDB_PORT=60756          # from the dashboard's Connectivity tab; NOT always 6379
FALKORDB_USERNAME=falkordb   # FalkorDB Cloud's user is "falkordb", not Redis' "default"
FALKORDB_PASSWORD=...
FALKORDB_TLS=false           # Free tier is not TLS

NVIDIA_API_KEY=...
NVIDIA_MODEL=z-ai/glm-5.3-flash
```

`.env` is git-ignored. Never commit credentials. Secrets have no defaults in
code on purpose: a missing key warns at startup instead of silently producing a
half-working agent (`GET /health` reports `missing_settings`).

**`LLM_ENABLED=false` runs the entire app with no model at all.** Every LLM node
has a deterministic fallback, so investigations still run end to end and return
an evidence-backed answer with citations. This is also how the test suite runs —
which is what keeps 218 tests free.

`LLM_PROVIDER` is `auto` (default), `nvidia`, or `google`. Naming a provider
whose key is missing raises rather than falling back, so a typo cannot quietly
spend the other account's quota. Google uses the real
`langchain-google-genai` client, not the OpenAI-compatibility shim.

### 3.2 Backend

```bash
cd backend
uv sync
uv run python -m app.seed.seed --reset     # 52 nodes / 124 relationships; --reset wipes first
uv run uvicorn app.main:app --port 8010 --reload
```

> **Use a port other than 8000.** This machine's agent harness polls
> `http://127.0.0.1:8000` once a second (`GET /health`, `GET /v1/models`) and has
> SIGKILLed the backend sitting there several times. Point the frontend at
> whatever port you pick, and start uvicorn with `--reload` — the session record
> shows a probe against a stale server that still had the old blocking route.

### 3.3 Frontend

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

If the backend is not on 8000, create `frontend/.env.local`:

```ini
NEXT_PUBLIC_API_BASE_URL=http://localhost:8010
```

The default lives at `frontend/lib/api.ts:25`. There is no `.env*` in
`frontend/` today, so the default is what you are getting.

**Browse via `localhost`, not `127.0.0.1`.** They are different origins to a
browser and the user's `.env` pins `CORS_ORIGINS=http://localhost:3000`; the
code's default allows both, but a pinned `.env` wins.

### 3.4 Tests

```bash
cd backend
uv run pytest                    # 218 tests, no model calls, no live database
uv run pytest -m integration     # only the tests that need live FalkorDB
uv run ruff check .
```

Frontend checks — **stop `next dev` first** (see §6):

```bash
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

---

## 4. The 60-second mental model

Two flows matter. Both are queued, both poll.

**An investigation**

```
POST /api/investigations            → 202 {investigation_id, poll_url}
   background thread:
     plan     classify intent, resolve the service names to ids
     retrieve run the allowlisted tools the intent implies
     assemble normalise evidence, collect explicit gaps
     write    model drafts the answer, or the deterministic writer does
     critic   audit every [id] against what was actually retrieved
     finalize apply the verdict (append verification notes if it qualified)
     memory   persist the investigation + CITED edges
GET /api/investigations/{id}/status  → steps so far, then the result
```

**An ingestion**

```
POST /api/ingest/file               → 202 {job_id, poll_url}
   background thread:
     convert  MarkItDown → Markdown (local, free)
     extract  model proposes entities/relationships → validated against allowlists
     write    upsert the document, new entities, relationships, DESCRIBES edges
GET /api/ingest/{job_id}/status     → phases as they finish, then the report
```

Both also accept `?wait=true`, which blocks and returns the whole payload — that
is what the tests and scripts use, and the path most likely to regress to inline
blocking, so it is tested for latency explicitly.

---

## 5. Repo map

```
backend/
  app/
    config.py         every knob and bound (one auditable place)
    llm.py            provider selection: nvidia | google | auto
    main.py           FastAPI app, CORS, routers
    graph/
      client.py       FalkorDB connection, ping, GraphUnavailable
      schema.py       unique constraints + full-text indexes
      queries.py      EVERY Cypher string in the app  ← the security boundary
      repository.py   typed, bounded methods over those queries
    agent/
      state.py        typed LangGraph state
      tools.py        the 10-tool allowlist + the per-run call budget
      nodes.py        the 7 node implementations
      prompts.py      planner / critic / writer prompts
      graph.py        pipeline assembly + run_investigation
      jobs.py         in-process job registry for investigations
    ingest/
      documents.py    MarkItDown conversion, size/extension guards
      extract.py      the LLM prompt + the validation allowlists
      service.py      ingest_document: convert → extract → write
      jobs.py         in-process job registry for ingestions
    api/
      errors.py       the one error envelope + exception handlers
      deps.py         the cached repository singleton
      routes/         health · graph · investigations · ingest
    models/           graph (domain) · api (contract) · ingest
    seed/             the synthetic company + the repeatable seeder
  tests/              conftest's FakeGraphRepository + 4 test modules
frontend/
  app/page.tsx        the dashboard (investigation report)
  app/graph/page.tsx  the graph browser: Graph + Table views
  components/         AnswerPanel · EvidencePanel · GraphCanvas · ImpactList
                      · StepsTimeline · HistoryList · IngestPanel
  lib/                api.ts (typed client) · types.ts · force.ts · examples.ts
docs/                 this file + KNOWLEDGE-TRANSFER.md + screenshots/
SPEC.md PHASES.md CHECKLIST.md README.md
```

**Suggested reading order** (about 90 minutes to a real mental model):

1. `README.md` — the pitch and the schema. (Read it knowing §8's drift.)
2. `app/models/graph.py` — the domain vocabulary. `Evidence`, `GraphPath` and
   `NodeRef` are what everything else speaks in.
3. `app/graph/queries.py` — the whole data layer in one file. Read the module
   docstring and the two conventions it names.
4. `app/agent/graph.py` then `app/agent/nodes.py` — the pipeline, in order.
5. `app/api/routes/investigations.py` — how a request becomes a job.
6. `frontend/app/page.tsx` — the client half of the same flow.
7. `SESSION_DUMP.md` (repo root, git-ignored, local only) — the working log:
   what was measured, what broke, what is still open. It is the most candid
   document in the repo; read §"Open" first.

---

## 6. Working in this repo

### Commands

| Command | What it does |
|---|---|
| `uv run uvicorn app.main:app --port 8010 --reload` | Backend, reloading |
| `uv run python -m app.seed.seed --reset` | Wipe and reseed the graph |
| `uv run pytest` | Full suite, offline, no model |
| `uv run pytest -m integration` | The subset that needs live FalkorDB |
| `uv run ruff check .` | Lint |
| `npm run dev` / `npm run build` / `npm run lint` | Frontend |

### The test approach, and why it matters

Tests never call a model. `tests/conftest.py` builds a `FakeGraphRepository`
from the *same* seed data and reproduces the Cypher semantics in Python —
including the reverse `DEPENDS_ON` traversal. The entire agent pipeline
therefore runs deterministically and for free. An autouse fixture forces
`LLM_ENABLED=false`.

Tests marked `integration` run the same assertions against real FalkorDB. That
is not ceremony: the in-memory model and the live driver disagreed several times
(`.result_set` returns positional rows, not dicts; FalkorDB rejects a parameter
inside a variable-length relationship range). Nothing short of a live run
surfaces that class of bug.

**Rule of thumb:** if you change a Cypher template, the in-memory fake probably
needs the matching change, or you will be testing your fake rather than the
database. Nine defects found this way are catalogued at the end of
`CHECKLIST.md`.

### Three ways to lose a dev server (all have happened)

1. **`npm run build` while `next dev` is serving the same directory.** The build
   rewrites `.next` underneath the dev server and it dies. Verify the build with
   the dev server stopped.
2. **`nohup … &` inside a shell call.** It does not survive. Use the shell
   tool's own background mode.
3. **Running the backend on port 8000.** The harness polls it and eventually
   kills whatever answers. See §3.2.

---

## 7. The one thing that can spoil the demo

As of this handoff, the configured `NVIDIA_MODEL` is a 550B NIM model. An
extraction prompt that asks for up to 40 entities does not finish inside the
client timeout (`AGENT_QUERY_TIMEOUT_SECONDS × 4` = 60s, retried twice, so
~3 minutes per call). The retry storm exhausts itself, the call returns empty,
and the document is stored with zero extracted entities.

The *reporting* was fixed: `invoke_with_reason` distinguishes three outcomes that
used to collapse into one empty string, so the panel now says
**"The model call failed — <reason>"** instead of the old, actively misleading
"No model was available". That is the good news: if you see that message, the
config is fine and the model is slow.

Two ways to actually fix the extraction, cheapest first:

1. **Point `NVIDIA_MODEL` at a smaller model.** No code change. `NVIDIA_MODEL`
   is user-managed — `.env` is the owner's, not the code's. Both
   `deepseek-ai/deepseek-v4.1-flash` and `z-ai/glm-5.3-flash` are on the same
   endpoint. This is the fix that unblocks the demo.
2. **Make `_invoke` honour its `timeout` argument**, so a dead call fails in
   seconds instead of minutes. Verified inert today: `timeout=2` against a 15s
   stub took 15.5s. Write a test against a stalling stub first.

Whatever you do, do not "fix" this by having the extractor claim success on an
empty response. The whole point of the failure-reporting change was that the app
admits a fault instead of blaming a setting that is fine.

---

## 8. Documentation drift (known)

The older docs were written before ingestion existed. These are the places they
are wrong, so you do not trust them over the code:

| Document | Stale claim | Reality |
|---|---|---|
| `README.md` architecture diagram | shows 6 API routes | 13, including four ingest routes, `/api/graph/full` and `/api/graph/entities` |
| `README.md` diagram | "14 parameterised Cypher templates" | 29 Cypher strings: 18 read, 6 memory, 5 ingest |
| `README.md` diagram + table | "11 relationship types"; `SUPPORTS` absent | 12 — `RelationType` has `SUPPORTS`, and `SUPPORTING_DOCUMENTS` queries `DESCRIBES` **or** `SUPPORTS` |
| `README.md` diagram | two boxes only ("NVIDIA NIM") | there is a provider abstraction: `nvidia` \| `google` \| `auto` |
| `.env.example` | `AGENT_MAX_TOOL_CALLS=12` | the code default is 24, deliberately raised because at 12 the primary demo exhausted its budget and skipped most of its own queries. Copying `.env.example` verbatim reintroduces that bug. |
| `CHECKLIST.md` | "all 14 templates" | as above |

Worth fixing when someone has a spare ten minutes; the read path count ("14")
was accurate when the diagram was drawn.

---

## 9. Next steps, in the order I would take them

1. **Unblock extraction** (§7, option 1) and re-run an upload against the live
   graph to prove entities land. This is the demo's remaining risk.
2. **Screenshots** of the redesigned dashboard and `/graph`. Every submission
   deliverable that mentions the UI needs one.
3. **Deploy.** Backend is a standard ASGI app, frontend a static Next build. Set
   `CORS_ORIGINS` to the frontend's exact origin (`localhost` and `127.0.0.1`
   are different origins) and `FALKORDB_TLS=true` above the Free tier.
4. **Demo video**, following the primary demo in `frontend/lib/examples.ts`
   (every example question there is a known-answer test the suite covers).
5. **DEV blog post** — the graph design and the reasoning workflow. The material
   is already written; it is spread across the README and the module docstrings.
6. **Triage the npm advisories**, or write down why you are not.
7. **Have someone follow the README cold**, on a different machine and OS.

---

## 10. House rules

- **Never let the LLM produce Cypher text.** Tools and templates only. A test
  asserts `execute_raw_cypher` does not exist.
- **Validate at the boundary.** Node labels and relationship types are
  interpolated into Cypher because Cypher cannot parameterise them; the only
  values allowed are members of `EntityType`/`RelationType`, and that check is
  enforced in *two* places (the extractor's allowlist, and again in
  `GraphRepository.upsert_entities` / `upsert_relationships`).
- **Never overwrite a curated entity.** Ingestion links to existing ids instead
  of restating them. A misreading must not be able to rewrite seeded facts.
- **Every LLM node needs a deterministic fallback.** The demo must survive a
  rate-limited endpoint, and the tests must run without one.
- **Nothing blocking on the event loop.** The ingestion pipeline is synchronous
  and goes through a worker thread in both the queued and the waiting path.
  There is a latency regression test for this, not a source-level assertion.
- **A failed call is not a missing key.** Keep the three-way distinction in
  `invoke_with_reason`.
- **Bounded everything.** The pipeline is acyclic, the toolbox has a budget, and
  LangGraph has a recursion limit. Three independent bounds, on purpose.
- **Advisory only.** Recommendations require human approval; nothing is executed.
- **All data is synthetic.** The company, its people and its incidents are
  invented; source URIs point at a reserved example domain.
