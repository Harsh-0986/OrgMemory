/**
 * Deterministic force-directed layout.
 *
 * Written by hand rather than pulled from a library for two reasons: the graph
 * is small (< 60 nodes, so the O(n^2) repulsion is free), and the demo needs a
 * *reproducible* picture. The same investigation must produce the same layout
 * every time it is shown, so initial positions are seeded from a hash of the
 * node id rather than from `Math.random`, and the simulation runs a fixed
 * number of iterations with no wall-clock dependence.
 */

export interface LayoutNode {
  id: string;
  type: string;
  name: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
  degree: number;
  fixed?: boolean;
}

export interface LayoutEdge {
  from: string;
  to: string;
  type: string;
}

export interface Layout {
  nodes: LayoutNode[];
  edges: Array<LayoutEdge & { source: LayoutNode; target: LayoutNode }>;
  width: number;
  height: number;
}

/** Cheap deterministic hash so a given id always starts in the same place. */
function hash(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return Math.abs(h);
}

const REPULSION = 5200;
const SPRING = 0.045;
const SPRING_LENGTH = 110;
const CENTER_PULL = 0.012;
const DAMPING = 0.82;
const ITERATIONS = 320;

/**
 * Compute a stable layout for a node/edge set.
 *
 * Nodes are seeded on a phyllotaxis spiral (evenly spread, no clustering by
 * chance) and then relaxed. Pinned nodes are excluded from the simulation so
 * a dragged node can be held in place.
 */
export function computeLayout(
  nodes: Array<{ id: string; type: string; name: string }>,
  edges: LayoutEdge[],
  width: number,
  height: number,
): Layout {
  const cx = width / 2;
  const cy = height / 2;
  const radius = Math.min(width, height) * 0.36;

  const layoutNodes: LayoutNode[] = nodes.map((node, index) => {
    // Golden-angle spiral: deterministic, well spread, no overlap at t=0.
    const angle = index * 2.399963;
    const r = radius * Math.sqrt((index + 0.5) / Math.max(1, nodes.length));
    return {
      ...node,
      x: cx + Math.cos(angle) * r,
      y: cy + Math.sin(angle) * r,
      vx: 0,
      vy: 0,
      degree: edges.filter((e) => e.from === node.id || e.to === node.id).length,
    };
  });

  const byId = new Map(layoutNodes.map((n) => [n.id, n]));
  const linked = edges
    .map((edge) => {
      const source = byId.get(edge.from);
      const target = byId.get(edge.to);
      return source && target ? { ...edge, source, target } : null;
    })
    .filter((e): e is NonNullable<typeof e> => e !== null);

  for (let step = 0; step < ITERATIONS; step += 1) {
    // Cool down slightly so the final iterations settle rather than oscillate.
    const cooling = 1 - (step / ITERATIONS) * 0.85;

    // Pairwise repulsion.
    for (let i = 0; i < layoutNodes.length; i += 1) {
      const a = layoutNodes[i];
      for (let j = i + 1; j < layoutNodes.length; j += 1) {
        const b = layoutNodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        let distSq = dx * dx + dy * dy;
        if (distSq < 0.01) {
          // Deterministic nudge for coincident nodes.
          dx = ((hash(a.id + b.id) % 100) - 50) / 10 || 0.5;
          dy = 0.5;
          distSq = dx * dx + dy * dy;
        }
        const dist = Math.sqrt(distSq);
        const force = REPULSION / distSq;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        a.vx -= fx;
        a.vy -= fy;
        b.vx += fx;
        b.vy += fy;
      }
    }

    // Spring attraction along edges.
    for (const edge of linked) {
      const dx = edge.target.x - edge.source.x;
      const dy = edge.target.y - edge.source.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = (dist - SPRING_LENGTH) * SPRING;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      edge.source.vx += fx;
      edge.source.vy += fy;
      edge.target.vx -= fx;
      edge.target.vy -= fy;
    }

    // Pull toward centre and integrate.
    for (const node of layoutNodes) {
      if (node.fixed) {
        node.vx = 0;
        node.vy = 0;
        continue;
      }
      node.vx += (cx - node.x) * CENTER_PULL;
      node.vy += (cy - node.y) * CENTER_PULL;
      node.x += node.vx * cooling;
      node.y += node.vy * cooling;
      node.vx *= DAMPING;
      node.vy *= DAMPING;
    }
  }

  return { nodes: layoutNodes, edges: linked, width, height };
}

/** Colour per entity type, used for nodes and legend chips. */
export const NODE_COLORS: Record<string, string> = {
  Service: "#38bdf8",
  Person: "#a78bfa",
  Incident: "#fb7185",
  Decision: "#fbbf24",
  Document: "#34d399",
  Project: "#f472b6",
  Investigation: "#94a3b8",
};

export const NODE_RADII: Record<string, number> = {
  Service: 13,
  Person: 11,
  Incident: 10,
  Decision: 10,
  Document: 9,
  Project: 10,
  Investigation: 10,
};

export function nodeColor(type: string): string {
  return NODE_COLORS[type] ?? "#94a3b8";
}

export function nodeRadius(type: string): number {
  return NODE_RADII[type] ?? 10;
}

/** Human label: prefer a real name, fall back to the id. */
export function labelFor(name: string, id: string): string {
  return (name || id).length > 26 ? `${(name || id).slice(0, 24)}…` : name || id;
}