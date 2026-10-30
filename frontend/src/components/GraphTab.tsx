import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import ForceGraph2D from "react-force-graph-2d";
import { ExternalLink, Network } from "lucide-react";
import { api } from "../lib/api";
import type { GraphNode } from "../lib/types";
import { Badge, Card, EmptyState, ErrorNote, Spinner } from "./ui";

const DEPTH_COLORS = ["#6d28d9", "#2563eb", "#0891b2", "#059669", "#ca8a04"];

function depthColor(depth: number) {
  return DEPTH_COLORS[Math.min(depth, DEPTH_COLORS.length - 1)];
}

export default function GraphTab() {
  const { workspaceId } = useParams();
  const wrapRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const [width, setWidth] = useState(800);
  const [selected, setSelected] = useState<GraphNode | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["graph", workspaceId],
    queryFn: () => api.graph(workspaceId!),
  });

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) =>
      setWidth(entry.contentRect.width),
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, [data]);

  // The force simulation can settle at any time; nudge the viewport to fit a
  // few times after the data lands rather than relying solely on onEngineStop.
  useEffect(() => {
    if (!data?.nodes.length) return;
    const timers = [300, 900, 1800].map((ms) =>
      setTimeout(() => graphRef.current?.zoomToFit(400, 70), ms),
    );
    return () => timers.forEach(clearTimeout);
  }, [data, width]);

  // react-force-graph mutates the objects it is given, so hand it copies.
  const graphData = useMemo(
    () => ({
      nodes: (data?.nodes ?? []).map((n) => ({ ...n })),
      links: (data?.edges ?? []).map((e) => ({ ...e })),
    }),
    [data],
  );

  const paintNode = useCallback(
    (node: any, ctx: CanvasRenderingContext2D, scale: number) => {
      const radius = 3 + Math.min(7, Math.sqrt(node.chunk_count ?? 1));
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = depthColor(node.depth ?? 0);
      ctx.fill();
      if (selected?.id === node.id) {
        ctx.strokeStyle = "#f43f5e";
        ctx.lineWidth = 2 / scale;
        ctx.stroke();
      }
      if (scale > 1.1) {
        const label = String(node.title ?? "").slice(0, 34);
        ctx.font = `${11 / scale}px ui-sans-serif, system-ui`;
        ctx.textAlign = "center";
        ctx.fillStyle = "#8f8f9a";
        ctx.fillText(label, node.x, node.y + radius + 9 / scale);
      }
    },
    [selected],
  );

  if (isLoading) {
    return (
      <Card>
        <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted">
          <Spinner /> Loading graph…
        </div>
      </Card>
    );
  }
  if (error) return <ErrorNote error={error} />;

  if (!data?.nodes.length) {
    return (
      <Card>
        <EmptyState
          icon={<Network size={34} strokeWidth={1.2} />}
          title="No graph yet"
          hint="Crawl a site in 'Whole site' mode — the graph is built from the internal links between the pages that were crawled."
        />
      </Card>
    );
  }

  const maxDepth = Math.max(...data.nodes.map((n) => n.depth));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold text-ink">
            <Network size={18} className="text-brand" />
            Knowledge graph
          </h1>
          <p className="mt-1 text-sm text-muted">
            Every crawled page, linked by the internal links between them.
            Node size is how many chunks the page contributed; colour is how
            many links it sits from the seed page.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge>{data.nodes.length} pages</Badge>
          <Badge>{data.edges.length} links</Badge>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <Card className="overflow-hidden">
          <div ref={wrapRef} className="h-[520px] w-full">
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData}
              width={width}
              height={520}
              backgroundColor="transparent"
              nodeLabel={(n: any) => `${n.title}\n${n.url}`}
              nodeCanvasObject={paintNode}
              nodePointerAreaPaint={(n: any, color, ctx) => {
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(n.x, n.y, 10, 0, 2 * Math.PI);
                ctx.fill();
              }}
              linkColor={() => "rgba(140,140,155,0.32)"}
              linkDirectionalArrowLength={3}
              linkDirectionalArrowRelPos={1}
              cooldownTicks={90}
              onEngineStop={() => graphRef.current?.zoomToFit(500, 70)}
              onNodeClick={(n: any) => setSelected(n as GraphNode)}
            />
          </div>
        </Card>

        <div className="space-y-3">
          <Card className="p-3">
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-faint">
              Link distance from seed
            </h3>
            <div className="space-y-1.5">
              {Array.from({ length: maxDepth + 1 }, (_, d) => (
                <div key={d} className="flex items-center gap-2 text-xs">
                  <span
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ background: depthColor(d) }}
                  />
                  <span className="text-muted">
                    {d === 0 ? "seed page" : `${d} link${d === 1 ? "" : "s"} away`}
                  </span>
                  <span className="ml-auto font-mono text-faint">
                    {data.nodes.filter((n) => n.depth === d).length}
                  </span>
                </div>
              ))}
            </div>
          </Card>

          {selected ? (
            <Card className="p-3">
              <p className="text-sm font-medium text-ink">{selected.title}</p>
              <a
                href={selected.url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 flex items-center gap-1 break-all text-[11px] text-brand hover:underline"
              >
                {selected.url} <ExternalLink size={10} className="shrink-0" />
              </a>
              <dl className="mt-3 space-y-1 border-t border-line pt-2 text-xs">
                <div className="flex justify-between">
                  <dt className="text-muted">Chunks indexed</dt>
                  <dd className="font-mono text-ink">
                    {selected.chunk_count ?? 0}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted">Characters</dt>
                  <dd className="font-mono text-ink">
                    {selected.char_count.toLocaleString()}
                  </dd>
                </div>
                <div className="flex justify-between">
                  <dt className="text-muted">Links from seed</dt>
                  <dd className="font-mono text-ink">{selected.depth}</dd>
                </div>
              </dl>
            </Card>
          ) : (
            <Card>
              <EmptyState
                title="No page selected"
                hint="Click a node to inspect the page it represents."
              />
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
