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

/** Zoom bounds. Beyond 6x labels collide; below 0.4x nothing is legible. */
const MIN_ZOOM = 0.4;
const MAX_ZOOM = 6;

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

  // Viewport: a viewBox over the laid-out graph, so zooming and panning cost
  // no re-layout and no re-render of the simulation.
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 });
  // Mirrors of the latest view/zoom handler for the native wheel listener,
  // which is attached once and must not close over stale state.
  const viewRef = useRef(view);
  const wheelRef = useRef<
    ((event: WheelEvent, current: { x: number; y: number; scale: number }) => void) | null
  >(null);
  /** Detaches the wheel listener from the previous SVG node, if any. */
  const wheelCleanup = useRef<(() => void) | null>(null);
  const panRef = useRef<{
    pointerX: number;
    pointerY: number;
    viewX: number;
    viewY: number;
  } | null>(null);
  const [panning, setPanning] = useState(false);

  // A new investigation should start framed, not wherever the last one was left.
  const signature = nodes.map((n) => n.id).join("|");
  const lastSignature = useRef(signature);
  useEffect(() => {
    if (lastSignature.current !== signature) {
      lastSignature.current = signature;
      setView({ x: 0, y: 0, scale: 1 });
      setDragged({});
    }
  }, [signature]);

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

  /** Client pixels -> graph units, honouring the current viewBox. */
  const toGraphAt = (
    clientX: number,
    clientY: number,
    current: { x: number; y: number; scale: number },
  ) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    const vbWidth = width / current.scale;
    const vbHeight = height / current.scale;
    return {
      x: current.x + ((clientX - rect.left) / rect.width) * vbWidth,
      y: current.y + ((clientY - rect.top) / rect.height) * vbHeight,
    };
  };

  const toGraph = (clientX: number, clientY: number) =>
    toGraphAt(clientX, clientY, view);

  const zoomTo = (nextScale: number, anchorX: number, anchorY: number) => {
    const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, nextScale));
    setView((prev) => {
      if (clamped === prev.scale) return prev;
      // Keep the point under the cursor fixed while the scale changes.
      const ratio = clamped / prev.scale;
      return {
        scale: clamped,
        x: anchorX - (anchorX - prev.x) * ratio,
        y: anchorY - (anchorY - prev.y) * ratio,
      };
    });
  };

  /**
   * Wheel zooms toward the pointer. ctrl+wheel is the trackpad pinch gesture.
   *
   * This has to be a native listener. React attaches `wheel` passively at the
   * root, so the `preventDefault()` in a JSX `onWheel` is ignored - which is
   * why the graph zoomed and the page scrolled underneath it at the same time.
   * Only a non-passive listener on the element can claim the gesture.
   */
  const zoomWithWheel = (event: WheelEvent, current: typeof view) => {
    event.preventDefault();
    const point = toGraphAt(event.clientX, event.clientY, current);
    zoomTo(
      current.scale * Math.exp(-event.deltaY * 0.0015),
      point.x,
      point.y,
    );
  };

  // Kept fresh after every render so the listener below never reads stale
  // state. Refs cannot be written during render, so this runs as an effect.
  useEffect(() => {
    viewRef.current = view;
    wheelRef.current = zoomWithWheel;
  });

  /**
   * A callback ref rather than an effect, because the SVG only exists once the
   * graph data has arrived. An effect with `[]` deps runs while the empty state
   * is still showing, finds no node, and never runs again - which is how the
   * listener silently failed to attach.
   */
  const attachWheelZoom = useCallback((node: SVGSVGElement | null) => {
    wheelCleanup.current?.();
    wheelCleanup.current = null;
    svgRef.current = node;
    if (!node) return;

    const onWheel = (event: WheelEvent) => {
      wheelRef.current?.(event, viewRef.current);
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    wheelCleanup.current = () => node.removeEventListener("wheel", onWheel);
  }, []);

  /** Dragging the background pans; dragging a node moves that node instead. */
  const handlePanStart = (event: React.PointerEvent) => {
    panRef.current = {
      pointerX: event.clientX,
      pointerY: event.clientY,
      viewX: view.x,
      viewY: view.y,
    };
    setPanning(true);
    (event.currentTarget as Element).setPointerCapture?.(event.pointerId);
  };

  const handlePanMove = (event: React.PointerEvent) => {
    const pan = panRef.current;
    const svg = svgRef.current;
    if (!pan || !svg) return;
    const rect = svg.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    // Dragging the canvas moves the *content* with the pointer, the way a map
    // or a canvas does: dragging left pulls the graph left, which means the
    // viewport origin moves right. Adding the delta instead would slide the
    // graph the opposite way to the cursor.
    const dx = ((event.clientX - pan.pointerX) / rect.width) * (width / view.scale);
    const dy = ((event.clientY - pan.pointerY) / rect.height) * (height / view.scale);
    setView((prev) => ({ ...prev, x: pan.viewX - dx, y: pan.viewY - dy }));
  };

  const stopPan = () => {
    panRef.current = null;
    setPanning(false);
  };

  const zoomByStep = (factor: number) => {
    const centre = toGraph(
      (svgRef.current?.getBoundingClientRect().left ?? 0) +
        (svgRef.current?.getBoundingClientRect().width ?? 0) / 2,
      (svgRef.current?.getBoundingClientRect().top ?? 0) +
        (svgRef.current?.getBoundingClientRect().height ?? 0) / 2,
    );
    zoomTo(view.scale * factor, centre.x, centre.y);
  };

  const handlePointerDown = (event: React.PointerEvent, id: string) => {
    event.stopPropagation();
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
        ref={attachWheelZoom}
        viewBox={`${view.x} ${view.y} ${width / view.scale} ${height / view.scale}`}
        className={`w-full touch-none select-none ${panning ? "cursor-grabbing" : "cursor-grab"}`}
        style={{ height }}
        tabIndex={-1}
        focusable="false"
        // The plate is a picture, not a control surface. Without this the
        // browser can hand arrow-key scrolling to a focused SVG, which looks
        // like the graph quietly panning itself.
        onKeyDown={(e) => {
          if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(e.key)) {
            e.preventDefault();
          }
        }}
        onPointerDown={handlePanStart}
        onPointerMove={(e) => {
          handlePointerMove(e);
          handlePanMove(e);
        }}
        onPointerUp={() => {
          dragRef.current = null;
          stopPan();
        }}
        onPointerLeave={() => {
          dragRef.current = null;
          stopPan();
        }}
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
              tabIndex={-1}
              focusable="false"
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
        <span className="ml-auto flex items-center gap-3">
          <span className="font-ui text-[0.68rem] text-plate-rule/70">
            drag to pan · scroll to zoom · click a node to focus
          </span>
          <span className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => zoomByStep(1 / 1.4)}
              aria-label="Zoom out"
              className="border border-plate-rule px-1.5 py-0.5 font-mono text-[0.7rem] text-plate-rule transition hover:border-plate-rule hover:text-white"
            >
              −
            </button>
            <span className="min-w-[3ch] text-center font-mono text-[0.65rem] text-plate-rule/70">
              {Math.round(view.scale * 100)}%
            </span>
            <button
              type="button"
              onClick={() => zoomByStep(1.4)}
              aria-label="Zoom in"
              className="border border-plate-rule px-1.5 py-0.5 font-mono text-[0.7rem] text-plate-rule transition hover:border-plate-rule hover:text-white"
            >
              +
            </button>
            <button
              type="button"
              onClick={() => {
                setView({ x: 0, y: 0, scale: 1 });
                setDragged({});
              }}
              aria-label="Reset view"
              className="border border-plate-rule px-1.5 py-0.5 font-mono text-[0.68rem] text-plate-rule transition hover:border-plate-rule hover:text-white"
            >
              reset
            </button>
          </span>
        </span>
      </div>
    </div>
  );
}