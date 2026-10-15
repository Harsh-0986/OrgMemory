"use client";

/**
 * Interactive SVG graph of the retrieved subgraph.
 *
 * Deliberately dependency-free: the layout comes from `lib/force.ts`, so the
 * only rendering work is SVG. Nodes can be dragged, and clicking a node (or a
 * citation chip elsewhere on the page) focuses it and highlights the dependency
 * paths that pass through it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  computeLayout,
  labelFor,
  nodeColor,
  nodeRadius,
  type LayoutNode,
} from "@/lib/force";
import type { Edge, GraphPath, NodeRef } from "@/lib/types";

interface GraphCanvasProps {
  nodes: NodeRef[];
  edges: Edge[];
  paths: GraphPath[];
  highlightedId?: string | null;
  onSelect?: (id: string | null) => void;
  height?: number;
}

export default function GraphCanvas({
  nodes,
  edges,
  paths,
  highlightedId,
  onSelect,
  height = 420,
}: GraphCanvasProps) {
  const [width, setWidth] = useState(720);
  const wrapRef = useRef<HTMLDivElement>(null);
  /**
   * Only user-driven node positions live in state. Laid-out positions are
   * derived in the `useMemo` below rather than mirrored into state through an
   * effect, which would cascade a render on every layout change.
   */
  const [dragged, setDragged] = useState<Record<string, { x: number; y: number }>>({});
  const dragRef = useRef<{ id: string; offsetX: number; offsetY: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // Responsive width without a resize library.
  useEffect(() => {
    const element = wrapRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const next = entries[0]?.contentRect.width;
      if (next) setWidth(Math.max(320, next));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const layout = useMemo(() => {
    if (nodes.length === 0) {
      return { nodes: [], edges: [], width, height };
    }
    const uniqueNodes = Array.from(
      new Map(nodes.map((n) => [n.id, n])).values(),
    );
    const edgeList = Array.from(
      new Map(
        edges.map((e) => [`${e.type}:${e.from_id}->${e.to_id}`, e] as const),
      ).values(),
    );
    return computeLayout(
      uniqueNodes,
      edgeList.map((e) => ({ from: e.from_id, to: e.to_id, type: e.type })),
      width,
      height,
    );
  }, [nodes, edges, width, height]);

  // Final positions: the computed layout with any dragged node pinned on top.
  const positions = useMemo(() => {
    const map: Record<string, LayoutNode> = {};
    for (const node of layout.nodes) {
      const override = dragged[node.id];
      map[node.id] = override ? { ...node, x: override.x, y: override.y } : node;
    }
    return map;
  }, [layout, dragged]);

  // Edges follow the same positions so a dragged node drags its edges too.
  const drawnEdges = useMemo(
    () =>
      layout.edges
        .map((edge) => ({
          ...edge,
          source: positions[edge.source.id] ?? edge.source,
          target: positions[edge.target.id] ?? edge.target,
        }))
        .filter((edge) => edge.source && edge.target),
    [layout.edges, positions],
  );

  /** Ids that participate in a highlighted path or the focused node. */
  const focusIds = useMemo(() => {
    const ids = new Set<string>();
    if (highlightedId) {
      ids.add(highlightedId);
      for (const edge of edges) {
        if (edge.from_id === highlightedId) ids.add(edge.to_id);
        if (edge.to_id === highlightedId) ids.add(edge.from_id);
      }
    }
    for (const path of paths) {
      const touches = path.nodes.some((n) => n.id === highlightedId);
      if (!highlightedId || touches) {
        path.nodes.forEach((n) => ids.add(n.id));
      }
    }
    return ids;
  }, [highlightedId, paths, edges]);

  const toLocal = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    return { x: clientX - rect.left, y: clientY - rect.top };
  }, []);

  const handlePointerDown = (event: React.PointerEvent, id: string) => {
    const point = toLocal(event.clientX, event.clientY);
    const node = positions[id];
    if (!node) return;
    dragRef.current = { id, offsetX: point.x - node.x, offsetY: point.y - node.y };
    (event.target as Element).setPointerCapture?.(event.pointerId);
  };

  const handlePointerMove = (event: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const point = toLocal(event.clientX, event.clientY);
    setDragged((prev) => ({
      ...prev,
      [drag.id]: { x: point.x - drag.offsetX, y: point.y - drag.offsetY },
    }));
  };

  const handlePointerUp = () => {
    dragRef.current = null;
  };

  if (nodes.length === 0) {
    return (
      <div
        ref={wrapRef}
        className="flex items-center justify-center rounded-xl border border-dashed border-slate-700 bg-slate-900/40 text-sm text-slate-500"
        style={{ height }}
      >
        No graph retrieved for this question yet.
      </div>
    );
  }

  const isDimmed = focusIds.size > 0;
  const legendTypes = Array.from(new Set(nodes.map((n) => n.type)));

  return (
    <div ref={wrapRef} className="space-y-3">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="w-full touch-none rounded-xl border border-slate-800 bg-slate-950"
        style={{ height }}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        role="img"
        aria-label={`Dependency graph with ${nodes.length} nodes and ${edges.length} edges`}
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#475569" />
          </marker>
          <marker
            id="arrow-hi"
            viewBox="0 0 10 10"
            refX="9"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#38bdf8" />
          </marker>
        </defs>

        {/* Edges */}
        {drawnEdges.map((edge) => {
          const highlighted = isDimmed && focusIds.has(edge.source.id) && focusIds.has(edge.target.id);
          return (
            <line
              key={`${edge.type}-${edge.source.id}-${edge.target.id}`}
              x1={edge.source.x}
              y1={edge.source.y}
              x2={edge.target.x}
              y2={edge.target.y}
              stroke={highlighted ? "#38bdf8" : "#334155"}
              strokeWidth={highlighted ? 2 : 1}
              strokeOpacity={isDimmed && !highlighted ? 0.25 : 0.9}
              markerEnd={highlighted ? "url(#arrow-hi)" : "url(#arrow)"}
            />
          );
        })}

        {/* Nodes */}
        {layout.nodes.map((node) => {
          const active = focusIds.has(node.id);
          const dimmed = isDimmed && !active;
          const isFocused = highlightedId === node.id;
          const r = nodeRadius(node.type);
          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              className="cursor-grab"
              onPointerDown={(e) => handlePointerDown(e, node.id)}
              onClick={() => onSelect?.(isFocused ? null : node.id)}
              opacity={dimmed ? 0.3 : 1}
            >
              {isFocused && (
                <circle r={r + 7} fill="none" stroke="#38bdf8" strokeWidth={2} opacity={0.8} />
              )}
              <circle
                r={r}
                fill={nodeColor(node.type)}
                fillOpacity={0.22}
                stroke={nodeColor(node.type)}
                strokeWidth={isFocused ? 2.5 : 1.5}
              />
              <text
                y={r + 13}
                textAnchor="middle"
                className="pointer-events-none select-none"
                fontSize="10"
                fill="#cbd5e1"
              >
                {labelFor(node.name, node.id)}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="flex flex-wrap items-center gap-3 text-[11px] text-slate-400">
        {legendTypes.map((type) => (
          <span key={type} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: nodeColor(type) }}
            />
            {type}
          </span>
        ))}
        <span className="ml-auto text-slate-500">
          Drag to rearrange · click a node to focus
        </span>
      </div>
    </div>
  );
}