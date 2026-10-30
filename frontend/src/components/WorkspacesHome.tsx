import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Globe, Layers, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { Badge, Button, Card, EmptyState, ErrorNote, STATUS_TONE, Spinner } from "./ui";

export default function WorkspacesHome() {
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState<string | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["workspaces"],
    queryFn: api.listWorkspaces,
    refetchInterval: 6_000,
  });

  const remove = async (id: string) => {
    setDeleting(id);
    try {
      await api.deleteWorkspace(id);
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    } finally {
      setDeleting(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted">
        <Spinner /> Loading workspaces…
      </div>
    );
  }
  if (error) return <ErrorNote error={error} />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-semibold text-ink">Workspaces</h1>
        <p className="mt-1 text-sm text-muted">
          Each workspace is one crawled site with its own index. Use “New” to add
          another.
        </p>
      </div>

      {!data?.length ? (
        <Card>
          <EmptyState
            icon={<Boxes size={34} strokeWidth={1.2} />}
            title="No workspaces yet"
            hint="Create one from the “New” button above — point it at a docs site and it will crawl, index, and be ready to answer questions."
          />
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.map((w) => (
            <Card key={w.id} className="flex flex-col p-4 transition-shadow hover:shadow-md">
              <div className="mb-2 flex items-start justify-between gap-2">
                <Link
                  to={`/w/${w.id}/chat`}
                  className="truncate text-sm font-semibold text-ink hover:text-brand"
                >
                  {w.name}
                </Link>
                <Badge tone={STATUS_TONE[w.status] ?? "neutral"}>{w.status}</Badge>
              </div>

              <a
                href={w.seed_url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1 truncate text-[11px] text-muted hover:text-brand"
              >
                <Globe size={11} className="shrink-0" />
                {w.seed_url}
              </a>

              {w.error && (
                <p className="mt-2 line-clamp-2 text-[11px] text-bad">{w.error}</p>
              )}

              <div className="mt-3 flex items-center gap-3 border-t border-line pt-2.5 text-[11px] text-muted">
                <span className="flex items-center gap-1">
                  <Layers size={11} />
                  {w.page_count} page{w.page_count === 1 ? "" : "s"}
                </span>
                <span>
                  {w.chunk_count.toLocaleString()} chunk
                  {w.chunk_count === 1 ? "" : "s"}
                </span>
                <span className="ml-auto capitalize">{w.mode}</span>
              </div>

              <div className="mt-3 flex gap-2">
                <Link to={`/w/${w.id}/chat`} className="flex-1">
                  <Button variant="primary" className="w-full">
                    Open
                  </Button>
                </Link>
                <Button
                  variant="danger"
                  loading={deleting === w.id}
                  onClick={() => remove(w.id)}
                  aria-label={`Delete ${w.name}`}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
