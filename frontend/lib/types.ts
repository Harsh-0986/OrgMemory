/**
 * TypeScript mirrors of the backend response models.
 *
 * These are hand-maintained to match `app/models/api.py`. They exist so the
 * dashboard gets compile-time safety on the investigation payload instead of
 * `any`, which would hide exactly the contract bugs the backend tests catch.
 */

export type EntityType =
  | "Person"
  | "Service"
  | "Project"
  | "Incident"
  | "Decision"
  | "Document"
  | "Investigation";

export type RelationType =
  | "OWNS"
  | "WORKED_ON"
  | "USES"
  | "DEPENDS_ON"
  | "AFFECTED"
  | "CAUSED_BY"
  | "RESOLVED"
  | "AFFECTS"
  | "SUPERSEDES"
  | "DESCRIBES"
  | "SUPPORTS"
  | "CITED";

export interface NodeRef {
  id: string;
  type: EntityType;
  name: string;
  properties: Record<string, unknown>;
}

export interface Edge {
  type: RelationType;
  from_id: string;
  from_type: EntityType;
  to_id: string;
  to_type: EntityType;
}

export interface GraphPath {
  nodes: NodeRef[];
  edges: Edge[];
  explanation: string;
}

export interface Evidence {
  evidence_id: string;
  kind: string;
  summary: string;
  entities: NodeRef[];
  paths: GraphPath[];
  tool: string;
  confidence: "confirmed" | "inferred" | "unknown";
  source_ids: string[];
  caveats: string[];
}

export interface ImpactedService {
  service: NodeRef;
  depth: number;
  owners: NodeRef[];
  reasons: string[];
  criticality: string;
}

export interface Recommendation {
  action: string;
  rationale: string;
  evidence_ids: string[];
  suggested_reviewers: NodeRef[];
  requires_human_approval: boolean;
}

export interface ExecutionStep {
  node: string;
  title: string;
  status: "pending" | "running" | "completed" | "skipped" | "failed";
  detail: string;
  tool: string;
  duration_ms: number;
  evidence_count: number;
  graph_paths: number;
}

export interface Critique {
  verdict: "pass" | "qualify";
  unsupported_claims: string[];
  contradictions: string[];
  missing_evidence: string[];
  notes: string;
}

export interface IncidentRow {
  id: string;
  title: string;
  severity: string;
  occurred_at: string;
  summary: string;
  root_cause_known: boolean;
  service_id: string;
  service_name: string;
  cause_ids: string[];
  cause_names: string[];
  resolver_ids: string[];
  resolver_names: string[];
}

export interface DecisionRow {
  id: string;
  title: string;
  date: string;
  rationale: string;
  status: string;
  service_id: string;
  service_name: string;
  superseded_by_ids: string[];
  superseded_by_titles: string[];
}

export interface DocumentRow {
  id: string;
  title: string;
  source_type: string;
  source_uri: string;
  content: string;
  entity_id: string;
  entity_name: string;
  entity_label: string;
  relation_type: string;
}

export interface EngineerRow {
  person_id: string;
  person_name: string;
  person_role: string;
  person_team: string;
  project_id: string;
  project_name: string;
  project_status: string;
  service_id: string;
  service_name: string;
  reason: string;
}

export interface InvestigationResponse {
  investigation_id: string;
  question: string;
  status: "pending" | "running" | "completed" | "failed";
  answer: string;
  confidence: "low" | "moderate" | "high";
  intent: string;
  evidence: Evidence[];
  graph_paths: GraphPath[];
  impacted_services: ImpactedService[];
  owners: Record<string, NodeRef[]>;
  engineers: EngineerRow[];
  incidents: IncidentRow[];
  decisions: DecisionRow[];
  documents: DocumentRow[];
  shared_dependencies: DocumentRow[];
  recommendations: Recommendation[];
  recalled_investigations: InvestigationSummary[];
  critique: Critique | null;
  steps: ExecutionStep[];
  cited_ids: string[];
  error: string | null;
}

export interface InvestigationSummary {
  id: string;
  question: string;
  created_at: string | null;
  summary: string;
  cited_ids: string[];
}

export interface InvestigationHistory {
  total: number;
  investigations: InvestigationSummary[];
}

export interface GraphOverview {
  graph: string;
  node_counts: Record<string, number>;
  relationship_counts: Record<string, number>;
  total_nodes: number;
  total_relationships: number;
  criticality_breakdown: Record<string, number>;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
    detail: string | null;
  };
}