"""Allowlisted Cypher query templates.

This module is the security boundary of the whole application. The LLM never
sees, generates, or influences Cypher text - it can only select from the tool
names registered in `app.agent.tools`, each of which calls a method here with
validated arguments. Every template is a module-level constant and every
user-supplied value travels through the `params` dict.

Two conventions matter for correctness:

* **Impact traverses DEPENDS_ON backwards.** `(A)-[:DEPENDS_ON]->(B)` means A
  breaks if B breaks, so asking "what breaks if B changes" means matching
  services that point *into* the changed service.
* **Paths are returned as flat maps** (`node_ids`, `rel_types`, `depth`) rather
  than native path objects, so the client never has to guess at serialisation
  details and every hop stays inspectable.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings

# --------------------------------------------------------------------------
# Read queries
# --------------------------------------------------------------------------

# Node/relationship projections keep the client from having to know about
# FalkorDB's internal representation.
_NODE_PROJECTION = (
    "[n IN nodes(p) | {id: n.id, label: head(labels(n))}]"
)
_REL_PROJECTION = "[r IN relationships(p) | type(r)]"

#: Impacted services, with the shortest hop count from the changed service.
#:
#: `{max_depth}` is substituted by `build()` with a validated integer.
#: FalkorDB rejects a query parameter inside a variable-length relationship
#: range - `[:DEPENDS_ON*1..$max_depth]` fails with "Encountered unhandled
#: type in inlined properties" - so the bound must be a literal. `build()`
#: clamps to a Python `int` before formatting, so no string can reach it.
DEPENDENCY_IMPACT = """
MATCH p = (impacted:Service)-[:DEPENDS_ON*1..{max_depth}]->(target:Service {{id: $service_id}})
WITH impacted, min(length(p)) AS depth
RETURN
  impacted.id AS id,
  impacted.name AS name,
  impacted.description AS description,
  impacted.criticality AS criticality,
  impacted.tier AS tier,
  depth
ORDER BY depth ASC, impacted.criticality ASC, id ASC
LIMIT $limit
"""

#: The actual dependency paths, so the UI can draw and highlight them.
#:
#: A plain string, not an f-string: every slot is filled by `build()` in one
#: pass. Mixing f-string interpolation with `str.format` yields templates whose
#: `{id: $service_id}` map literals get mistaken for format placeholders.
DEPENDENCY_PATHS = """
MATCH p = (impacted:Service)-[:DEPENDS_ON*1..{max_depth}]->(target:Service {{id: $service_id}})
RETURN
  {nodes} AS nodes,
  {rels} AS rel_types,
  length(p) AS depth
ORDER BY depth ASC
LIMIT $limit
"""

#: Services the given service depends on (its own dependencies).
UPSTREAM_DEPENDENCIES = """
MATCH p = (target:Service {{id: $service_id}})-[:DEPENDS_ON*1..{max_depth}]->(dep:Service)
WITH dep, min(length(p)) AS depth
RETURN
  dep.id AS id,
  dep.name AS name,
  dep.description AS description,
  dep.criticality AS criticality,
  depth
ORDER BY depth ASC, id ASC
LIMIT $limit
"""

#: Shared dependencies - services both the old and new service depend on.
#: These are the real migration risks: shared infrastructure that must support
#: both paths simultaneously.
SHARED_DEPENDENCIES = """
MATCH (a:Service)-[:DEPENDS_ON]->(shared:Service)<-[:DEPENDS_ON]-(b:Service)
WHERE a.id = $a_id AND b.id = $b_id
RETURN DISTINCT
  shared.id AS id,
  shared.name AS name,
  shared.description AS description,
  shared.criticality AS criticality
ORDER BY id ASC
LIMIT $limit
"""

SERVICE_OWNERS = """
UNWIND $service_ids AS sid
MATCH (person:Person)-[:OWNS]->(service:Service {id: sid})
RETURN
  service.id AS service_id,
  service.name AS service_name,
  service.criticality AS criticality,
  person.id AS person_id,
  person.name AS person_name,
  person.role AS person_role,
  person.team AS person_team
ORDER BY service_id ASC, person_name ASC
LIMIT $limit
"""

#: People with hands-on history on projects that touch the impacted services,
#: plus anyone who resolved an incident on them.
RELEVANT_ENGINEERS = """
UNWIND $service_ids AS sid
MATCH (person:Person)-[:WORKED_ON]->(project:Project)-[:USES]->(service:Service {id: sid})
RETURN
  person.id AS person_id,
  person.name AS person_name,
  person.role AS person_role,
  person.team AS person_team,
  project.id AS project_id,
  project.name AS project_name,
  project.status AS project_status,
  service.id AS service_id,
  service.name AS service_name,
  'project' AS reason
UNION
UNWIND $service_ids AS sid
MATCH (person:Person)-[:RESOLVED]->(incident:Incident)-[:AFFECTED]->(service:Service {id: sid})
RETURN
  person.id AS person_id,
  person.name AS person_name,
  person.role AS person_role,
  person.team AS person_team,
  incident.id AS project_id,
  incident.title AS project_name,
  incident.severity AS project_status,
  service.id AS service_id,
  service.name AS service_name,
  'incident' AS reason
LIMIT $limit
"""

RELATED_INCIDENTS = """
UNWIND $service_ids AS sid
MATCH (incident:Incident)-[:AFFECTED]->(service:Service {id: sid})
OPTIONAL MATCH (incident)-[:CAUSED_BY]->(cause:Service)
OPTIONAL MATCH (resolver:Person)-[:RESOLVED]->(incident)
RETURN
  incident.id AS id,
  incident.title AS title,
  incident.severity AS severity,
  incident.occurred_at AS occurred_at,
  incident.summary AS summary,
  incident.root_cause_known AS root_cause_known,
  service.id AS service_id,
  service.name AS service_name,
  collect(DISTINCT cause.id) AS cause_ids,
  collect(DISTINCT cause.name) AS cause_names,
  collect(DISTINCT resolver.id) AS resolver_ids,
  collect(DISTINCT resolver.name) AS resolver_names
ORDER BY occurred_at DESC
LIMIT $limit
"""

DECISION_HISTORY = """
UNWIND $service_ids AS sid
MATCH (decision:Decision)-[:AFFECTS]->(service:Service {id: sid})
OPTIONAL MATCH (superseding:Decision)-[:SUPERSEDES]->(decision)
RETURN
  decision.id AS id,
  decision.title AS title,
  decision.date AS date,
  decision.rationale AS rationale,
  decision.status AS status,
  service.id AS service_id,
  service.name AS service_name,
  collect(DISTINCT superseding.id) AS superseded_by_ids,
  collect(DISTINCT superseding.title) AS superseded_by_titles
ORDER BY date DESC
LIMIT $limit
"""

SUPPORTING_DOCUMENTS = """
UNWIND $entity_ids AS eid
MATCH (doc:Document)-[rel]->(entity)
WHERE entity.id = eid AND type(rel) IN ['DESCRIBES', 'SUPPORTS']
RETURN
  doc.id AS id,
  doc.title AS title,
  doc.source_type AS source_type,
  doc.source_uri AS source_uri,
  doc.content AS content,
  entity.id AS entity_id,
  entity.name AS entity_name,
  head(labels(entity)) AS entity_label,
  type(rel) AS relation_type
ORDER BY id ASC
LIMIT $limit
"""

#: Candidate replacement services, ranked by the caller's description of them.
#: Matching is fuzzy and read-only - it only proposes `service_id` values that
#: the caller then confirms by exact id.
SERVICE_SEARCH = """
MATCH (s:Service)
WHERE toLower(s.name) CONTAINS toLower($needle)
   OR toLower(s.id) CONTAINS toLower($needle)
   OR toLower(coalesce(s.description, '')) CONTAINS toLower($needle)
RETURN
  s.id AS id,
  s.name AS name,
  s.description AS description,
  s.criticality AS criticality,
  s.tier AS tier
ORDER BY
  CASE WHEN toLower(s.name) = toLower($needle) THEN 0
       WHEN toLower(s.id) = toLower($needle) THEN 0
       ELSE 1 END ASC,
  s.name ASC
LIMIT $limit
"""

ENTITY_SEARCH = """
MATCH (n)
WHERE toLower(coalesce(n.name, n.title, '')) CONTAINS toLower($needle)
   OR toLower(n.id) CONTAINS toLower($needle)
RETURN
  n.id AS id,
  head(labels(n)) AS label,
  coalesce(n.name, n.title) AS name,
  $limit AS _unused
ORDER BY id ASC
LIMIT $limit
"""

#: Every entity of one label, optionally filtered by a free-text needle.
#:
#: No pagination: the demo graph is small enough to return whole, and a single
#: bounded round trip is kinder to the database than a paginated scan.
_LIST_TAIL = """
WHERE toLower(coalesce(n.name, n.title, '')) CONTAINS toLower($q)
   OR toLower(n.id) CONTAINS toLower($q)
RETURN n.id AS id, properties(n) AS props
ORDER BY id ASC
LIMIT $limit
"""


def list_entities_template(label: str) -> str:
    """Build the listing query for a label, from the fixed allowlist only.

    Cypher cannot bind a node label from a parameter, so the label has to be
    interpolated into the query text. Accepting only `EntityType` members is
    what makes that interpolation safe.
    """
    from app.models.graph import EntityType

    allowed = {e.value for e in EntityType}
    if label not in allowed:
        raise ValueError(f"Unknown node label '{label}'")
    return f"MATCH (n:{label})\n{_LIST_TAIL}"


#: Every node and every edge, for the whole-graph view.
#:
#: Bounded by `LIMIT` because this is the one query that is not scoped to a
#: label or an entity. It is a demo-scale graph, so a single bounded pass is
#: cheaper and simpler than paginating.
ALL_NODES = """
MATCH (n)
RETURN n.id AS id, head(labels(n)) AS label, coalesce(n.name, n.title, n.id) AS name
ORDER BY id ASC
LIMIT $limit
"""

ALL_EDGES = """
MATCH (a)-[r]->(b)
RETURN a.id AS from_id, type(r) AS rel_type, b.id AS to_id
ORDER BY from_id ASC, rel_type ASC
LIMIT $limit
"""

GRAPH_OVERVIEW = """
MATCH (n)
RETURN head(labels(n)) AS label, count(n) AS count
ORDER BY count DESC
LIMIT $limit
"""

GRAPH_EDGE_COUNTS = """
MATCH (a)-[r]->(b)
RETURN type(r) AS rel_type, count(r) AS count
ORDER BY count DESC
LIMIT $limit
"""

GRAPH_NEIGHBORHOOD = """
MATCH p = (entity)-[*1..{max_depth}]-(neighbour)
WHERE entity.id = $entity_id
RETURN
  {nodes} AS nodes,
  {rels} AS rel_types,
  length(p) AS depth
ORDER BY depth ASC
LIMIT $limit
"""

#: Look up a single entity of any label by its exact id.
ENTITY_BY_ID = """
MATCH (n {id: $entity_id})
RETURN n.id AS id, head(labels(n)) AS label, properties(n) AS props
LIMIT 1
"""

# --------------------------------------------------------------------------
# Memory queries
# --------------------------------------------------------------------------

PREVIOUS_INVESTIGATIONS = """
MATCH (inv:Investigation)
WHERE inv.status IN ['completed', 'failed']
RETURN
  inv.id AS id,
  inv.question AS question,
  inv.created_at AS created_at,
  inv.answer AS answer,
  inv.summary AS summary,
  inv.cited_ids AS cited_ids
ORDER BY inv.created_at DESC
LIMIT $limit
"""

#: Rank past investigations by how many question terms they share.
#: Term matching is done in Python to keep the Cypher simple and portable.
STORE_INVESTIGATION = """
CREATE (inv:Investigation)
SET inv = $props
RETURN inv.id AS id
"""

LINK_CITATIONS = """
MATCH (inv:Investigation {id: $investigation_id})
UNWIND $citations AS citation
MATCH (target {id: citation.id})
MERGE (inv)-[:CITED]->(target)
RETURN count(*) AS linked
"""

INVESTIGATION_BY_ID = """
MATCH (inv:Investigation {id: $investigation_id})
RETURN inv.id AS id, properties(inv) AS props
LIMIT 1
"""

INVESTIGATION_CITATIONS = f"""
MATCH p = (inv:Investigation)-[:CITED]->(cited)
WHERE inv.id = $investigation_id
RETURN
  {_NODE_PROJECTION} AS nodes,
  {_REL_PROJECTION} AS rel_types,
  length(p) AS depth
LIMIT $limit
"""

#: Wipe all investigation memory (dev utility / test isolation).
CLEAR_INVESTIGATIONS = """
MATCH (inv:Investigation)
DETACH DELETE inv
RETURN count(inv) AS deleted
"""


def build(template: str, depth: int | None = None) -> str:
    """Fill a template's traversal-depth slot with a validated integer.

    FalkorDB will not accept a parameter inside a variable-length relationship
    range, so the hop bound has to be baked into the query string. `depth` is
    coerced to `int` and clamped by `max_depth()` first, which makes the
    substitution safe: a non-numeric value cannot survive to be formatted.

    The only other placeholders are module constants (`{nodes}`, `{rels}`).
    """
    return template.format(
        max_depth=max_depth(depth),
        nodes=_NODE_PROJECTION,
        rels=_REL_PROJECTION,
    )


def default_limit(default: int = 50, ceiling: int | None = None) -> int:
    """Clamp a caller-supplied limit.

    Defaults to `GRAPH_MAX_RESULTS`, which is right for per-entity queries but
    too small for whole-graph reads: clamping those to 100 would silently show
    a truncated graph. Pass an explicit `ceiling` for those.
    """
    cap = ceiling if ceiling is not None else get_settings().graph_max_results
    return min(max(1, default), cap)


def max_depth(requested: int | None = None) -> int:
    """Clamp a requested traversal depth to the configured ceiling.

    The result is interpolated into the Cypher string by `build()`, so it must
    always be a real `int`. A non-numeric value falls back to the ceiling
    rather than raising, which guarantees nothing but an integer can reach the
    template.
    """
    ceiling = get_settings().graph_max_dependency_depth
    if requested is None:
        return ceiling
    try:
        value = int(requested)
    except (TypeError, ValueError):
        return ceiling
    return min(max(1, value), ceiling)


def row_to_dict(row: Any) -> dict[str, Any]:
    """Normalise a FalkorDB result row into a plain dictionary."""
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "properties"):  # a bare node was returned
        return dict(row.properties)
    return {"value": row}