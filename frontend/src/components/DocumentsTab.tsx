import { useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Database,
  FileText,
  Hash,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { api } from "../lib/api";
import { cleanSnippet } from "../lib/citations";
import { useJobProgress } from "../lib/useJobProgress";
import { Badge, Button, Card, EmptyState, ErrorNote, Spinner, cn } from "./ui";

function Stat({
  icon,
  value,
  label,
}: {
  icon: React.ReactNode;
  value: React.ReactNode;
  label: string;
}) {
  return (
    <Card className="flex items-center gap-3 p-4">
      <span className="text-brand">{icon}</span>
      <div>
        <div className="text-xl font-semibold leading-tight text-ink">
          {value}
        </div>
        <div className="text-[11px] text-muted">
          {label}
        </div>
      </div>
    </Card>
  );
}

export default function DocumentsTab() {
  const { workspaceId } = useParams();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);

  const { job } = useJobProgress(jobId);
  const rebuilding = !!job && !["succeeded", "failed", "cancelled"].includes(job.status);

  const workspace = useQuery({
    queryKey: ["workspace", workspaceId],
    queryFn: () => api.getWorkspace(workspaceId!),
  });

  const docs = useQuery({
    queryKey: ["documents", workspaceId, page, query],
    queryFn: () => api.documents(workspaceId!, page, 25, query || undefined),
  });

  const reindex = async (recrawl: boolean) => {
    const j = await api.reindex(workspaceId!, recrawl);
    setJobId(j.id);
  };

  if (job?.status === "succeeded" && jobId) {
    setJobId(null);
    queryClient.invalidateQueries({ queryKey: ["documents", workspaceId] });
    queryClient.invalidateQueries({ queryKey: ["workspace", workspaceId] });
    queryClient.invalidateQueries({ queryKey: ["graph", workspaceId] });
  }

  const ws = workspace.data;
  const avg =
    docs.data && docs.data.documents.length
      ? Math.round(
          docs.data.documents.reduce((a, d) => a + d.length, 0) /
            docs.data.documents.length,
        )
      : 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted">
            {ws ? (
              <>
                Indexed chunks from{" "}
                <a
                  href={ws.seed_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-brand hover:underline"
                >
                  {ws.seed_url}
                </a>
              </>
            ) : (
              "Indexed chunks for this workspace"
            )}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={() => reindex(false)} disabled={rebuilding}>
            <RefreshCw size={14} className={cn(rebuilding && "animate-spin")} />
            Re-index
          </Button>
          <Button variant="primary" onClick={() => reindex(true)} disabled={rebuilding}>
            <RefreshCw size={14} />
            Re-crawl
          </Button>
        </div>
      </div>

      {ws?.error && <ErrorNote error={ws.error} />}

      {job && rebuilding && (
        <Card className="p-3">
          <div className="mb-2 flex items-center justify-between text-xs">
            <span className="font-medium text-body">{job.phase || job.status}</span>
            <span className="text-muted">{job.message}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-brand transition-all duration-300"
              style={{ width: `${job.percent ?? 8}%` }}
            />
          </div>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          icon={<Database size={18} />}
          value={docs.data?.total_chunks.toLocaleString() ?? "—"}
          label="Chunks indexed"
        />
        <Stat
          icon={<FileText size={18} />}
          value={ws?.page_count ?? "—"}
          label="Pages crawled"
        />
        <Stat
          icon={<Hash size={18} />}
          value={avg ? avg.toLocaleString() : "—"}
          label="Avg chunk chars"
        />
      </div>

      <Card>
        <div className="flex items-center gap-2 border-b border-line p-3">
          <div className="relative flex-1">
            <Search
              size={14}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  setQuery(search);
                  setPage(1);
                }
              }}
              placeholder="Filter chunks by text…"
              className="w-full rounded-lg border border-line bg-canvas py-1.5 pl-9 pr-3 text-sm text-ink placeholder:text-faint focus:border-brand focus:outline-none"
            />
          </div>
          {query && (
            <Button
              variant="ghost"
              onClick={() => {
                setSearch("");
                setQuery("");
                setPage(1);
              }}
            >
              <Trash2 size={13} /> Clear
            </Button>
          )}
        </div>

        {docs.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted">
            <Spinner /> Loading chunks…
          </div>
        ) : docs.isError ? (
          <div className="p-4">
            <ErrorNote error={docs.error} />
          </div>
        ) : !docs.data?.documents.length ? (
          <EmptyState
            icon={<FileText size={34} strokeWidth={1.2} />}
            title={query ? "No chunks match that filter" : "No documents indexed yet"}
            hint={
              query
                ? "Try a different search term."
                : "Crawl a site to populate the index."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-line bg-canvas text-[11px] text-muted">
                  <th className="px-4 py-2.5 font-medium">Source</th>
                  <th className="px-4 py-2.5 font-medium">Section</th>
                  <th className="px-4 py-2.5 font-medium">Preview</th>
                  <th className="px-4 py-2.5 text-right font-medium">Chars</th>
                </tr>
              </thead>
              <tbody>
                {docs.data.documents.map((d, i) => (
                  <tr
                    key={d.id ?? i}
                    className="animate-fade-rise border-b border-line last:border-0 hover:bg-canvas"
                    style={{ animationDelay: `${Math.min(i, 12) * 18}ms` }}
                  >
                    <td className="max-w-[14rem] px-4 py-2.5">
                      <a
                        href={d.source_url}
                        target="_blank"
                        rel="noreferrer"
                        className="block truncate text-xs text-brand hover:underline"
                        title={d.source_url}
                      >
                        {d.page_title || d.source_url}
                      </a>
                      <span className="text-[11px] text-faint">
                        chunk #{d.chunk_index}
                      </span>
                    </td>
                    <td className="max-w-[12rem] px-4 py-2.5">
                      <span className="block truncate text-xs text-muted">
                        {d.heading || "—"}
                      </span>
                    </td>
                    <td className="max-w-[28rem] px-4 py-2.5">
                      <span className="block truncate text-xs text-body">
                        {cleanSnippet(d.summary)}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-right font-mono text-xs text-muted">
                      {d.length.toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {docs.data && docs.data.pages > 1 && (
          <div className="flex items-center justify-between border-t border-line px-4 py-2.5">
            <Badge>
              page {docs.data.page} of {docs.data.pages}
            </Badge>
            <div className="flex gap-1">
              <Button
                variant="ghost"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft size={14} /> Prev
              </Button>
              <Button
                variant="ghost"
                disabled={page >= docs.data.pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next <ChevronRight size={14} />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
