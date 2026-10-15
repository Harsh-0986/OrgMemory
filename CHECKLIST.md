# OrgMemory — Implementation Checklists

## 1. Project Setup

- [ ] Repository created.
- [ ] `.gitignore` configured.
- [ ] `.env.example` created.
- [ ] Python environment configured.
- [ ] FastAPI starts successfully.
- [ ] Next.js starts successfully.
- [ ] FalkorDB starts successfully.
- [ ] Backend can connect to FalkorDB.
- [ ] README contains local setup instructions.

## 2. Graph Database

- [ ] `Person` nodes seeded.
- [ ] `Service` nodes seeded.
- [ ] `Project` nodes seeded.
- [ ] `Incident` nodes seeded.
- [ ] `Decision` nodes seeded.
- [ ] `Document` nodes seeded.
- [ ] `Investigation` model implemented.
- [ ] Ownership relationships created.
- [ ] Project relationships created.
- [ ] Service dependencies created.
- [ ] Incident relationships created.
- [ ] Decision relationships created.
- [ ] Evidence provenance recorded.
- [ ] Seed script is repeatable.
- [ ] Graph contains meaningful multi-hop paths.

## 3. Graph Query Tools

- [ ] Dependency traversal works.
- [ ] Traversal depth is bounded.
- [ ] Impacted services are returned.
- [ ] Service owners are returned.
- [ ] Relevant engineers are returned.
- [ ] Related incidents are returned.
- [ ] Architecture decisions are returned.
- [ ] Supporting documents are returned.
- [ ] Results include stable IDs.
- [ ] Relationship paths are preserved.
- [ ] Query templates are parameterized.
- [ ] Arbitrary LLM-generated Cypher is not executed.
- [ ] Empty results are handled correctly.
- [ ] Query tests pass.

## 4. FastAPI

- [ ] Health endpoint works.
- [ ] Graph overview endpoint works.
- [ ] Graph neighborhood endpoint works.
- [ ] Investigation creation endpoint works.
- [ ] Investigation retrieval endpoint works.
- [ ] Investigation history endpoint works.
- [ ] Request validation is implemented.
- [ ] Response schemas are documented.
- [ ] Errors are returned consistently.
- [ ] CORS is configured for local development.
- [ ] API tests pass.

## 5. LangGraph Agent

- [ ] Agent state is defined.
- [ ] Planner node works.
- [ ] Graph retrieval node works.
- [ ] Evidence assembly works.
- [ ] Critic node checks claims.
- [ ] Writer node generates the answer.
- [ ] Execution steps are observable.
- [ ] Tool calls are bounded.
- [ ] Errors do not create infinite loops.
- [ ] Unsupported claims are rejected or qualified.
- [ ] Unknown information is reported explicitly.
- [ ] Agent output includes evidence references.
- [ ] Known-answer tests pass.

## 6. Persistent Memory

- [ ] Investigation IDs are unique.
- [ ] Questions are stored.
- [ ] Summaries are stored.
- [ ] Evidence references are stored.
- [ ] Timestamps are stored.
- [ ] Previous investigations can be retrieved.
- [ ] Follow-up questions can reference earlier findings.
- [ ] Memory persists after backend restart.
- [ ] Missing history is handled gracefully.

## 7. Frontend

- [ ] Main dashboard renders.
- [ ] Question input works.
- [ ] Example questions work.
- [ ] Loading state is visible.
- [ ] Errors are understandable.
- [ ] Agent execution steps are displayed.
- [ ] Answer is displayed.
- [ ] Evidence panel is displayed.
- [ ] Source references are inspectable.
- [ ] Graph visualization renders.
- [ ] Relevant paths are highlighted.
- [ ] Impacted services are displayed.
- [ ] Owners and reviewers are displayed.
- [ ] Investigation history works.
- [ ] Empty states are implemented.
- [ ] Layout works on desktop and mobile.

## 8. Primary Demo: Payment Migration

- [ ] Payment Service A exists.
- [ ] Payment Service B exists.
- [ ] Checkout and billing dependencies exist.
- [ ] Service owners are defined.
- [ ] Relevant engineers have project history.
- [ ] At least one related incident exists.
- [ ] At least one architecture decision exists.
- [ ] Decision rationale has a source record.
- [ ] Agent discovers multi-hop dependencies.
- [ ] Agent identifies reviewers using graph evidence.
- [ ] Agent identifies relevant incidents.
- [ ] Agent explains the current architecture decision.
- [ ] Agent produces a migration checklist.
- [ ] Each major claim has supporting evidence.
- [ ] Unverified risks are labelled as potential risks.
- [ ] Follow-up investigation can recall previous findings.

## 9. Quality and Reliability

- [ ] No unsupported ownership claims.
- [ ] No invented dependencies.
- [ ] No unsupported causal claims.
- [ ] Contradictory evidence is surfaced.
- [ ] Missing evidence is surfaced.
- [ ] Graph traversal limits are enforced.
- [ ] API failures are handled.
- [ ] LLM failures are handled.
- [ ] Demo data is synthetic.
- [ ] Secrets are excluded from Git.
- [ ] Core workflow can be repeated reliably.

## 10. Submission

- [ ] Public repository is ready.
- [ ] README explains the problem and solution.
- [ ] Architecture is documented.
- [ ] Graph schema is documented.
- [ ] FalkorDB's role is clearly explained.
- [ ] Setup instructions are tested on a clean environment.
- [ ] Sample questions are included.
- [ ] Demo video is recorded.
- [ ] Demo link is working.
- [ ] Technical blog post is published.
- [ ] AI coding assistance is disclosed as required.
- [ ] Submission requirements are checked.
- [ ] Submission is completed before the deadline.
