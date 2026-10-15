# OrgMemory — Implementation Checklists

Status key: `[x]` done and verified · `[~]` partially done · `[ ]` not started

Last updated after the end-to-end run against a live FalkorDB Cloud instance.

---

## 1. Project Setup

- [x] Repository created. **Never pushed** — no git remote is configured, by design.
- [x] `.gitignore` configured.
- [x] `.env.example` created.
- [x] Python environment configured (`uv`, Python 3.12).
- [x] FastAPI starts successfully.
- [x] Next.js starts successfully.
- [x] FalkorDB starts successfully — **FalkorDB Cloud (free tier)**, no Docker used.
- [x] Backend can connect to FalkorDB.
- [x] README contains local setup instructions.

> **Docker note.** The spec's Phase 0 called for Docker. Docker was not available and
> FalkorDB Cloud was chosen instead, which removes the local database step entirely.

## 2. Graph Database

- [x] `Person` nodes seeded — 10
- [x] `Service` nodes seeded — 18
- [x] `Project` nodes seeded — 5
- [x] `Incident` nodes seeded — 6
- [x] `Decision` nodes seeded — 5
- [x] `Document` nodes seeded — 8
- [x] `Investigation` model implemented — written at runtime with real `CITED` edges
- [x] Ownership relationships created
- [x] Project relationships created
- [x] Service dependencies created — 124 seeded relationships total
- [x] Incident relationships created
- [x] Decision relationships created
- [x] Evidence provenance recorded — every node carries a stable id used as the citation key
- [x] Seed script is repeatable — `MERGE` upserts; `--reset` for a clean rebuild
- [x] Graph contains meaningful multi-hop paths — Storefront → Cart → Checkout → Payment A (3 hops)

## 3. Graph Query Tools

- [x] Dependency traversal works
- [x] Traversal depth is bounded — `GRAPH_MAX_DEPENDENCY_DEPTH`, default 3, max 6
- [x] Impacted services are returned
- [x] Service owners are returned
- [x] Relevant engineers are returned
- [x] Related incidents are returned
- [x] Architecture decisions are returned — including supersession chains
- [x] Supporting documents are returned
- [x] Shared dependencies returned — the migration risk surface
- [x] Results include stable IDs
- [x] Relationship paths are preserved
- [x] Query templates are parameterized — all 14 templates; depth is the one literal, coerced to `int` and clamped
- [x] Arbitrary LLM-generated Cypher is not executed — 10-tool allowlist; a test asserts `execute_raw_cypher` is absent
- [x] Empty results are handled correctly
- [x] Query tests pass — unit tests plus live-DB integration tests

## 4. FastAPI

- [x] Health endpoint works
- [x] Graph overview endpoint works
- [x] Graph neighborhood endpoint works
- [x] Investigation creation endpoint works
- [x] Investigation retrieval endpoint works
- [x] Investigation history endpoint works
- [x] Request validation is implemented
- [x] Response schemas are documented — available at `/docs`
- [x] Errors are returned consistently — one `{"error": {code, message, detail}}` envelope
- [x] CORS is configured for local development
- [x] API tests pass

## 5. LangGraph Agent

- [x] Agent state is defined
- [x] Planner node works — intent classification + service resolution
- [x] Graph retrieval node works — intent decides which queries run
- [x] Evidence assembly works
- [x] Critic node checks claims — deterministic citation audit plus model reasoning
- [x] Writer node generates the answer
- [x] Execution steps are observable — reducer accumulates them across nodes
- [x] Tool calls are bounded — budget of 24 per investigation
- [x] Errors do not create infinite loops — the pipeline is acyclic
- [x] Unsupported claims are rejected or qualified
- [x] Unknown information is reported explicitly
- [x] Agent output includes evidence references
- [x] Known-answer tests pass

> **Every LLM node has a deterministic fallback**, so the API returns an
> evidence-backed answer even with no model configured. `LLM_ENABLED=false`
> exercises that path; it is how the test suite runs.

## 6. Persistent Memory

- [x] Investigation IDs are unique
- [x] Questions are stored
- [x] Summaries are stored
- [x] Evidence references are stored — as real `CITED` edges, not a text blob
- [x] Timestamps are stored
- [x] Previous investigations can be retrieved
- [x] Follow-up questions can reference earlier findings — verified in the browser
- [x] Memory persists after backend restart — it lives in FalkorDB, not in process memory
- [x] Missing history is handled gracefully — empty state, not an error

## 7. Frontend

- [x] Main dashboard renders
- [x] Question input works
- [x] Example questions work
- [x] Loading state is visible
- [x] Errors are understandable
- [x] Agent execution steps are displayed
- [x] Answer is displayed
- [x] Evidence panel is displayed
- [x] Source references are inspectable — citations, chips and documents are all clickable
- [x] Graph visualization renders
- [x] Relevant paths are highlighted
- [x] Impacted services are displayed — depth shown as indentation
- [x] Owners and reviewers are displayed
- [x] Investigation history works
- [x] Empty states are implemented
- [x] Layout works on desktop and mobile
- [x] Light and dark themes, applied before first paint with no flash
- [x] `tsc` clean · `eslint` clean · production build succeeds

## 8. Primary Demo: Payment Migration

- [x] Payment Service A exists — `svc-payment-legacy`
- [x] Payment Service B exists — `svc-payment-v2`
- [x] Checkout and billing dependencies exist
- [x] Service owners are defined
- [x] Relevant engineers have project history
- [x] At least one related incident exists — 6 incidents across the payment path
- [x] At least one architecture decision exists — 4 apply to Payment Service A
- [x] Decision rationale has a source record — ADRs linked via `SUPPORTS`
- [x] Agent discovers multi-hop dependencies — 8 services across 3 hops
- [x] Agent identifies reviewers using graph evidence — from `OWNS` and `WORKED_ON`
- [x] Agent identifies relevant incidents
- [x] Agent explains the current architecture decision — including that it is superseded
- [x] Agent produces a migration checklist
- [x] Each major claim has supporting evidence
- [x] Unverified risks are labelled as potential risks
- [x] Follow-up investigation can recall previous findings

> **Dataset gaps the agent surfaces rather than hides:** Payment Service A depends on
> `svc-identity` and Payment Service B does not, with nothing recorded explaining the
> difference. `inc-2026-04-webhook-latency` has no recorded cause.

## 9. Quality and Reliability

- [x] No unsupported ownership claims
- [x] No invented dependencies
- [x] No unsupported causal claims
- [x] Contradictory evidence is surfaced — the critic reports them
- [x] Missing evidence is surfaced — explicit "what the graph does not record" panel
- [x] Graph traversal limits are enforced — and the depth slot is proven injection-safe
- [x] API failures are handled — graph and LLM outages both return 503
- [x] LLM failures are handled — deterministic fallback at every node
- [x] Demo data is synthetic
- [x] Secrets are excluded from Git
- [x] Core workflow can be repeated reliably

> `npm audit` reports 5 high-severity advisories in the Next.js dependency tree.
> **Not yet triaged.** `npm audit fix --force` was deliberately not run because it
> applies breaking changes.

## 10. Submission

- [~] Public repository is ready — code is complete and committed, but **not pushed** by
      instruction and no remote is configured.
- [x] README explains the problem and solution
- [x] Architecture is documented — diagram and data-flow in the README
- [x] Graph schema is documented
- [x] FalkorDB's role is clearly explained — four specific jobs, not hand-waving
- [~] Setup instructions are tested on a clean environment — verified on macOS with
      Python 3.12 and Node 24; not yet tested on another machine or OS.
- [x] Sample questions are included
- [ ] Demo video is recorded
- [ ] Demo link is working — not deployed
- [ ] Technical blog post is published
- [x] AI coding assistance is disclosed — noted in the README
- [x] Submission requirements are checked
- [ ] Submission is completed before the deadline

---

## Known gaps, in priority order

1. **5 npm vulnerabilities** untriaged in the Next.js tree.
2. **No deployment.** Both halves build cleanly, but nothing is hosted, so there is no
   public demo link.
3. **No demo video.**
4. **Setup instructions untested on a second machine.** Worth having someone follow
   the README cold before the deadline.
5. **No screenshots of the redesigned UI.** The earlier captures predate the redesign
   and were removed rather than shipped stale.
6. **Blog post not written.**

---

## Bugs found by testing

Recorded because the shape of these failures is the argument for the test approach.
Nine defects were caught before a judge could see them.

| # | Defect | Found by |
|---|---|---|
| 1 | Circular dependency in seed data (`cart → checkout` *and* `checkout → cart`) | dataset integrity test |
| 2 | Execution steps silently discarded — LangGraph replaces lists per node | pipeline test |
| 3 | Incident and ownership questions queried an empty service list | intent-routing test |
| 4 | `dict.fromkeys` on Pydantic models → `TypeError`, crashed every replacement question | recommendation test |
| 5 | Recall matched on filler words, surfacing unrelated investigations | memory test |
| 6 | Duplicate response models → every investigation endpoint returned 500 | API test |
| 7 | Driver returns positional rows, not dicts → **every live query returned garbage** | integration test |
| 8 | FalkorDB rejects parameters in variable-length patterns | integration test |
| 9 | Path query f-string collided with `str.format` → impact analysis silently returned zero | live demo run |

Defect 7 is the argument for this design: the in-memory repository agreed with itself
while the real driver disagreed. Nothing short of running against FalkorDB surfaced it.