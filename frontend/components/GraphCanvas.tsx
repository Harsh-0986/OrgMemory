"use client";

/**
 * The dependency graph, as a dark plate inset in the light document.
 *
 * This is the one element on the page allowed its own surface, because it is
 * the one thing that is genuinely a different kind of object - a plotted
 * figure rather than a paragraph. Everything else stays on paper.
 *
 * Layout comes from `lib/force.ts`, so there is no plotting dependency, and it
 * is seeded deterministically: the same investigation renders identically every
 * time, which matters when you are demoing.
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
  height = 460,
}: GraphCanvasProps) {
  const [width, setWidth] = useState(720);
  const wrapRef = useRef<HTMLDivElement>(null);
  /** Only user-dragged positions are state; the rest is derived. */
  const [dragged, setDragged] = useState<Record<string, { x: number; y: number }>>({});
  const dragRef = useRef<{ id: string; offsetX: number; offsetY: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

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
    if (nodes.length === 0) return { nodes: [], edges: [], width, height };
    const uniqueNodes = Array.from(new Map(nodes.map((n) => [n.id, n])).values());
    const edgeList = Array.from(
      new Map(edges.map((e) => [`${e.type}:${e.from_id}->${e.to_id}`, e] as const)).values(),
    );
    return computeLayout(
      uniqueNodes,
      edgeList.map((e) => ({ from: e.from_id, to: e.to_id, type: e.type })),
      width,
      height,
    );
  }, [nodes, edges, width, height]);

  const positions = useMemo(() => {
    const map: Record<string, LayoutNode> = {};
    for (const node of layout.nodes) {
      const override = dragged[node.id];
      map[node.id] = override ? { ...node, x: override.x, y: override.y } : node;
    }
    return map;
  }, [layout, dragged]);

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

  /** Ids implicated by the focus, or by the paths that support the answer. */
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
      if (!highlightedId || touches) path.nodes.forEach((n) => ids.add(n.id));
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

  if (nodes.length === 0) {
    return (
      <div
        ref={wrapRef}
        className="flex items-center justify-center bg-plate text-sm text-plate-rule"
        style={{ height }}
      >
        No graph retrieved for this question yet.
      </div>
    );
  }

  const isDimmed = focusIds.size > 0;
  const legendTypes = Array.from(new Set(nodes.map((n) => n.type)));

  return (
    <div ref={wrapRef} className="bg-plate">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${width} ${height}`}
        className="w-full touch-none"
        style={{ height }}
        onPointerMove={handlePointerMove}
        onPointerUp={() => (dragRef.current = null)}
        onPointerLeave={() => (dragRef.current = null)}
        role="img"
        aria-label={`Dependency graph with ${nodes.length} nodes and ${edges.length} edges`}
      >
        <defs>
          <marker id="plate-arrow" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#4a5563" />
          </marker>
          <marker id="plate-arrow-hi" viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#8fb8dd" />
          </marker>
        </defs>

        {drawnEdges.map((edge) => {
          const lit = isDimmed && focusIds.has(edge.source.id) && focusIds.has(edge.target.id);
          return (
            <line
              key={`${edge.type}-${edge.source.id}-${edge.target.id}`}
              x1={edge.source.x}
              y1={edge.source.y}
              x2={edge.target.x}
              y2={edge.target.y}
              stroke={lit ? "#8fb8dd" : "#39424d"}
              strokeWidth={lit ? 1.4 : 0.8}
              strokeOpacity={isDimmed && !lit ? 0.22 : 0.85}
              markerEnd={lit ? "url(#plate-arrow-hi)" : "url(#plate-arrow)"}
            />
          );
        })}

        {layout.nodes.map((node) => {
          const active = focusIds.has(node.id);
          const dimmed = isDimmed && !active;
          const focused = highlightedId === node.id;
          const r = nodeRadius(node.type);
          return (
            <g
              key={node.id}
              transform={`translate(${node.x}, ${node.y})`}
              className="cursor-grab"
              onPointerDown={(e) => handlePointerDown(e, node.id)}
              onClick={() => onSelect?.(focused ? null : node.id)}
              opacity={dimmed ? 0.26 : 1}
            >
              {focused && (
                <circle r={r + 7} fill="none" stroke="#8fb8dd" strokeWidth={1.5} opacity={0.75} />
              )}
              <circle
                r={r}
                fill={nodeColor(node.type)}
                fillOpacity={focused ? 0.34 : 0.16}
                stroke={nodeColor(node.type)}
                strokeWidth={focused ? 2 : 1.2}
              />
              <text
                y={r + 12}
                textAnchor="middle"
                className="pointer-events-none select-none"
                fontSize="9.5"
                fontFamily="var(--font-plex-sans)"
                fill="#cbd2d9"
              >
                {labelFor(node.name, node.id)}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-plate-rule px-3 py-2">
        {legendTypes.map((type) => (
          <span key={type} className="flex items-center gap-1.5 font-ui text-[0.68rem] text-plate-rule">
            <span
              className="h-1.5 w-1.5 rounded-full"
              style={{ backgroundColor: nodeColor(type) }}
            />
            {type}
          </span>
        ))}
        <span className="ml-auto font-ui text-[0.68rem] text-plate-rule/70">
          drag to rearrange · click a node to focus
        </span>
      </div>
    </div>
  );
}