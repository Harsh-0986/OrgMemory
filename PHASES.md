# OrgMemory — Development Phases

## Phase 0: Scope and Setup

**Goal:** Establish a reproducible development environment.

- [ ] Create repository and project structure.
- [ ] Set up Python environment and dependencies.
- [ ] Set up Next.js and TypeScript.
- [ ] Start FalkorDB using Docker.
- [ ] Verify database connectivity.
- [ ] Add environment variable examples.
- [ ] Write initial README.

**Deliverable:** All services start locally.

## Phase 1: Graph Model and Seed Data

**Goal:** Build the knowledge graph before implementing the agent.

- [ ] Define node labels and properties.
- [ ] Define relationship types.
- [ ] Create synthetic company data.
- [ ] Seed people, services, projects, incidents, decisions, and documents.
- [ ] Create realistic dependency chains.
- [ ] Add source IDs and provenance metadata.
- [ ] Implement graph initialization scripts.
- [ ] Test seeded data with Cypher queries.

**Deliverable:** A connected, queryable company graph.

## Phase 2: Graph Query Layer

**Goal:** Make company knowledge accessible through tested functions.

- [ ] Implement dependency traversal.
- [ ] Implement service ownership lookup.
- [ ] Implement relevant engineer discovery.
- [ ] Implement related incident lookup.
- [ ] Implement architecture decision retrieval.
- [ ] Implement supporting document retrieval.
- [ ] Return structured entities and relationship paths.
- [ ] Add traversal depth and result limits.
- [ ] Test every query against known expected results.

**Deliverable:** Reliable graph tools independent of the LLM.

## Phase 3: FastAPI Backend

**Goal:** Expose the graph functionality through a stable API.

- [ ] Implement `GET /health`.
- [ ] Implement `GET /api/graph/overview`.
- [ ] Implement `GET /api/graph/neighborhood`.
- [ ] Define Pydantic request and response models.
- [ ] Add structured error responses.
- [ ] Add investigation data models.
- [ ] Add API tests.

**Deliverable:** A functioning API connected to FalkorDB.

## Phase 4: LangGraph Agent

**Goal:** Build an evidence-grounded investigation workflow.

- [ ] Define typed agent state.
- [ ] Implement the planner node.
- [ ] Register allowlisted graph query tools.
- [ ] Implement the graph retrieval node.
- [ ] Normalize results into evidence records.
- [ ] Implement the critic node.
- [ ] Implement the answer writer.
- [ ] Track execution steps and tool results.
- [ ] Add bounded retries and execution limits.
- [ ] Test questions with known answers.

**Deliverable:** The agent answers company questions using graph data.

## Phase 5: Persistent Memory

**Goal:** Preserve investigations between sessions.

- [ ] Generate unique investigation IDs.
- [ ] Store questions and final summaries.
- [ ] Store cited entity IDs and evidence references.
- [ ] Store timestamps and investigation status.
- [ ] Implement history retrieval.
- [ ] Retrieve previous investigations in follow-up questions.
- [ ] Test that memory survives a backend restart.

**Deliverable:** A later session can retrieve and build on previous findings.

## Phase 6: Frontend Dashboard

**Goal:** Make graph reasoning visible to judges.

- [ ] Build the main investigation page.
- [ ] Add question input and example prompts.
- [ ] Display agent execution steps.
- [ ] Display the final answer.
- [ ] Display evidence and source references.
- [ ] Render graph nodes and edges.
- [ ] Highlight paths supporting key claims.
- [ ] Show impacted services and owners.
- [ ] Add investigation history.
- [ ] Add loading, error, and empty states.
- [ ] Make the interface responsive.

**Deliverable:** A polished, interactive end-to-end experience.

## Phase 7: Demo and Validation

**Goal:** Prove that FalkorDB materially drives the result.

- [ ] Prepare the payment-service migration scenario.
- [ ] Verify expected dependency paths.
- [ ] Verify expected owners and decisions.
- [ ] Test a question requiring multiple graph hops.
- [ ] Test missing and contradictory evidence.
- [ ] Test investigation recall across sessions.
- [ ] Ensure every major claim has evidence.
- [ ] Verify the agent does not invent causal relationships.
- [ ] Record a fallback demo video.

**Deliverable:** A reliable, evidence-backed demo.

## Phase 8: Submission and Blog

**Goal:** Prepare the project for judging and the side prize.

- [ ] Finalize the public repository.
- [ ] Complete setup and architecture documentation.
- [ ] Add sample questions and expected results.
- [ ] Add a clear architecture diagram.
- [ ] Deploy the demo if feasible.
- [ ] Record the final demo video.
- [ ] Write the technical blog post.
- [ ] Explain the role of FalkorDB and graph traversal.
- [ ] Disclose AI coding assistance as required by the rules.
- [ ] Verify the submission requirements.
- [ ] Submit before the deadline.

**Deliverable:** A complete hackathon submission.
