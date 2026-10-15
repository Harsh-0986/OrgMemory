# OrgMemory — Product & Technical Specification

## Overview

OrgMemory is an AI-powered Company Brain built for Graph Hacks, powered by FalkorDB.

It connects people, projects, services, incidents, documents, and architecture decisions into a knowledge graph. Users can ask complex questions about their engineering organization and receive answers grounded in connected data, with traceable evidence.

**Track:** Company Brain  
**Tagline:** Your company's knowledge, connected and explainable.

## Problem

Company knowledge is fragmented across documentation, logs, tickets, and team members. Traditional chatbots often retrieve isolated snippets but fail to understand how systems and decisions relate.

OrgMemory uses FalkorDB to enable multi-hop reasoning, persistent investigation memory, and evidence-backed answers.

## Goals

- Use FalkorDB as the primary graph context layer.
- Answer questions requiring multi-hop reasoning.
- Connect people, services, projects, incidents, and decisions.
- Trace answers back to supporting evidence.
- Remember previous investigations across sessions.
- Provide an interactive graph visualization.
- Demonstrate that graph relationships materially influence agent decisions.

## Non-Goals

- Production-grade integrations with every company tool.
- Autonomous production deployments or infrastructure changes.
- Enterprise billing and complex access control.
- A generic chatbot without graph-grounded reasoning.

## Primary Demo

A team wants to replace Payment Service A with Payment Service B.

User asks:

"Can we replace Payment Service A with Payment Service B? What could break, who should review it, and why do we use the current service?"

The agent should:

1. Find direct and indirect service dependencies.
2. Identify owners and engineers with relevant experience.
3. Retrieve previous incidents and architecture decisions.
4. Assess potential impact using graph relationships.
5. Recommend reviewers and migration checks.
6. Explain the reasoning with evidence and graph paths.
7. Save the investigation for future sessions.

All demo data must be synthetic and internally consistent.

## Target Users

- Software engineers
- Engineering managers
- Technical leads
- Incident responders
- Platform and infrastructure teams

## MVP Features

### 1. Company Knowledge Graph

Represent company knowledge as connected entities in FalkorDB.

### 2. Natural Language Investigation

Users ask questions in natural language. The agent identifies the question type and selects appropriate graph queries.

### 3. Dependency Analysis

Traverse service dependencies to determine which systems could be affected by a change.

### 4. Ownership Discovery

Identify service owners and engineers with relevant project experience.

### 5. Incident Investigation

Connect incidents to affected services, related dependencies, and documented resolutions.

### 6. Decision Traceability

Retrieve architecture decisions and supporting documents.

### 7. Persistent Memory

Save investigation summaries, references, and timestamps. Allow later sessions to retrieve previous findings.

### 8. Explainable Answers

Every material claim should link to supporting graph records or source documents. Explicitly label unknown or unsupported conclusions.

### 9. Interactive Dashboard

Display the answer, evidence sources, graph paths, impacted systems, and recommended next steps.

## Graph Schema

### Nodes

- `Person`: id, name, role, team
- `Service`: id, name, description, criticality
- `Project`: id, name, status
- `Incident`: id, title, severity, occurred_at, summary
- `Decision`: id, title, date, rationale, status
- `Document`: id, title, source_type, source_uri, content
- `Investigation`: id, question, created_at, summary

### Relationships

- `(Person)-[:OWNS]->(Service)`
- `(Person)-[:WORKED_ON]->(Project)`
- `(Project)-[:USES]->(Service)`
- `(Service)-[:DEPENDS_ON]->(Service)`
- `(Incident)-[:AFFECTED]->(Service)`
- `(Incident)-[:CAUSED_BY]->(Service)`
- `(Person)-[:RESOLVED]->(Incident)`
- `(Decision)-[:AFFECTS]->(Service)`
- `(Decision)-[:SUPERSEDES]->(Decision)`
- `(Document)-[:DESCRIBES]->(Service)`
- `(Document)-[:SUPPORTS]->(Decision)`
- `(Investigation)-[:CITED]->(Document)`
- `(Investigation)-[:CITED]->(Incident)`
- `(Investigation)-[:CITED]->(Decision)`
- `(Investigation)-[:CITED]->(Service)`
- `(Investigation)-[:CITED]->(Person)`

Only create causal relationships when the available evidence supports them.

## Agent Workflow

Implement with LangGraph.

1. Planner: classify the question and select an investigation strategy.
2. Graph Retriever: execute allowlisted, parameterized Cypher queries.
3. Evidence Assembler: normalize graph results and preserve provenance.
4. Critic: check claims against evidence and flag contradictions.
5. Writer: generate a concise answer with findings and recommendations.
6. Memory: persist the investigation and its cited entities.

The workflow must have bounded execution and must not allow arbitrary database commands generated by the LLM.

## Required Graph Queries

1. Direct and indirect service dependencies.
2. Ownership of impacted services.
3. Engineers with relevant project experience.
4. Related incidents.
5. Architecture decision history.
6. Supporting documents.
7. Previous investigation retrieval.

Return structured results with entity IDs and relationship paths where possible.

## API

- `GET /health`
- `GET /api/graph/overview`
- `GET /api/graph/neighborhood?entity_id=...`
- `POST /api/investigations`
- `GET /api/investigations/{investigation_id}`
- `GET /api/investigations/history`

The investigation endpoint accepts a question and returns an investigation ID, status, answer, evidence, and graph paths.

## Frontend

Build with Next.js, TypeScript, and Tailwind CSS.

Required views:

- Main investigation interface
- Answer and evidence panel
- Interactive graph visualization
- Impacted services and owners
- Investigation history
- Loading, error, and empty states

## Technology Stack

- Frontend: Next.js, TypeScript, Tailwind CSS
- Backend: Python, FastAPI
- Agent orchestration: LangGraph
- Graph database: FalkorDB
- LLM integration: LangChain-compatible model provider
- Validation: Pydantic and automated tests
- Deployment: Docker-based local setup, plus a public demo deployment if feasible

## Reliability and Safety

- Never invent ownership, dependencies, decisions, or incident causes.
- Distinguish confirmed facts from inferred risks.
- Include source IDs for material claims.
- Show when evidence is missing or conflicting.
- Limit traversal depth and result sizes.
- Use parameterized Cypher templates.
- Keep demo data synthetic.
- Treat suggested actions as recommendations requiring human review.

## Acceptance Criteria

- FalkorDB stores the core company graph.
- At least one question requires multi-hop traversal.
- Graph query results change the agent's answer.
- The answer displays supporting evidence.
- A previous investigation can be retrieved in a later session.
- The frontend visualizes relevant graph relationships.
- The primary demo runs reproducibly from documented instructions.
- Tests cover graph queries and evidence-grounding behavior.

## Hackathon Deliverables

- Public source repository
- Working demo
- Demo video
- README with setup instructions
- Architecture diagram
- Seed dataset
- Example questions and expected answers
- Technical blog post explaining the graph design and reasoning workflow
