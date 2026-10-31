import { Suspense, lazy } from "react";
import { Link, NavLink, Navigate, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, MessageSquare, RefreshCw, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { useJobProgress } from "../../lib/useJobProgress";
import ApiTab from "../ApiTab";
import DocumentsTab from "../DocumentsTab";
import RetrievalLabTab from "../RetrievalLabTab";
import { Button, ErrorNote, Spinner, cn } from "../ui";

// react-force-graph pulls in the whole d3 stack; keep it out of the main bundle.
const GraphTab = lazy(() => import("../GraphTab"));

const TABS = [
  ["lab", "Retrieval lab"],
  ["documents", "Pages and chunks"],
  ["graph", "Link graph"],
  ["api", "API"],
] as const;

export default function SitePage() {
  const { workspaceId, tab } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const site = useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: () => api.getWorkspace(workspaceId!),
    refetchInterval: (q) => (q.state.data && ["crawling", "indexing"].includes(q.state.data.status) ? 3000 : false),
  });
  const reindex = useMutation({
    mutationFn: () => api.reindex(workspaceId!, true),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId] }),
  });
  const { job } = useJobProgress(reindex.data?.id ?? null);

  if (!TABS.some(([key]) => key === tab)) return <Navigate to={`/sites/${workspaceId}/lab`} replace />;
  if (site.isLoading) return <div className="p-10"><Spinner /></div>;
  if (site.error || !site.data) return <div className="mx-auto max-w-xl p-10"><ErrorNote error={site.error ?? "No such site."} /></div>;

  const ws = site.data;
  const busy = ["crawling", "indexing"].includes(ws.status);

  return (
    <div className="mx-auto max-w-6xl px-5 pt-14 pb-16 md:pt-8">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <h1 className="font-serif text-[1.9rem] leading-tight font-semibold text-ink">{ws.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[14px] text-muted">
            <a href={ws.seed_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-brand">
              {ws.seed_url}
              <ExternalLink size={12} />
            </a>
            <span>{ws.page_count} pages</span>
            <span>{ws.chunk_count} passages</span>
            <span className={cn(ws.status === "ready" ? "text-good" : ws.status === "failed" ? "text-bad" : "text-warn")}>
              {busy && job?.message ? job.message : ws.status}
            </span>
          </p>
          {ws.error && <p className="mt-2 text-[13.5px] text-bad">{ws.error}</p>}
        </div>
        <div className="flex gap-2">
          <Link to={`/?site=${ws.id}`}>
            <Button variant="primary" disabled={!ws.chunk_count}>
              <MessageSquare size={15} />
              Ask this site
            </Button>
          </Link>
          <Button onClick={() => reindex.mutate()} loading={reindex.isPending} disabled={busy} title="Crawl again and rebuild the index">
            <RefreshCw size={15} />
            Re-crawl
          </Button>
          <Button
            variant="danger"
            aria-label="Delete site"
            onClick={async () => {
              if (!confirm(`Delete ${ws.name} and its index? Chats that used it keep their history.`)) return;
              await api.deleteWorkspace(ws.id);
              queryClient.invalidateQueries({ queryKey: ["workspaces"] });
              navigate("/sites");
            }}
          >
            <Trash2 size={15} />
          </Button>
        </div>
      </div>

      <nav className="mt-7 mb-6 flex gap-5 overflow-x-auto border-b border-line" aria-label="Site views">
        {TABS.map(([key, label]) => (
          <NavLink
            key={key}
            to={`/sites/${ws.id}/${key}`}
            className={({ isActive }) =>
              cn("-mb-px shrink-0 border-b-2 pb-2.5 text-[14.5px]", isActive ? "border-ink font-medium text-ink" : "border-transparent text-muted hover:text-ink")
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>

      {tab === "lab" && <RetrievalLabTab />}
      {tab === "documents" && <DocumentsTab />}
      {tab === "api" && <ApiTab />}
      {tab === "graph" && (
        <Suspense fallback={<div className="flex items-center gap-2 py-20 text-sm text-muted"><Spinner /> Loading graph…</div>}>
          <GraphTab />
        </Suspense>
      )}
    </div>
  );
}
