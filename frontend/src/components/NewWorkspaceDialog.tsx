import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Globe, Layers, X } from "lucide-react";
import { api } from "../lib/api";
import { useJobProgress } from "../lib/useJobProgress";
import type { CrawlMode } from "../lib/types";
import { Button, ErrorNote, cn } from "./ui";

export default function NewWorkspaceDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [url, setUrl] = useState("");
  const [mode, setMode] = useState<CrawlMode>("page");
  const [maxPages, setMaxPages] = useState(25);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [workspaceId, setWorkspaceId] = useState<string | null>(null);

  const { job } = useJobProgress(jobId);

  useEffect(() => {
    if (!open) {
      setUrl("");
      setError(null);
      setJobId(null);
      setWorkspaceId(null);
      setSubmitting(false);
    }
  }, [open]);

  useEffect(() => {
    if (job?.status === "succeeded" && workspaceId) {
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
      navigate(`/w/${workspaceId}/chat`);
      onClose();
    }
  }, [job?.status, workspaceId, navigate, onClose, queryClient]);

  if (!open) return null;

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await api.createWorkspace({
        seed_url: url.trim(),
        mode,
        max_pages: mode === "site" ? maxPages : undefined,
      });
      setWorkspaceId(res.workspace.id);
      setJobId(res.job?.id ?? null);
      queryClient.invalidateQueries({ queryKey: ["workspaces"] });
    } catch (err) {
      setError(err);
      setSubmitting(false);
    }
  };

  const busy = submitting || (!!job && !["succeeded", "failed", "cancelled"].includes(job.status));

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/45 p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-line bg-surface p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-ink">New workspace</h2>
            <p className="mt-0.5 text-xs text-muted">
              Crawl a site and index it. Each workspace is independent.
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-muted hover:bg-canvas hover:text-ink"
          >
            <X size={16} />
          </button>
        </div>

        <label className="mb-1.5 block text-xs font-medium text-body">
          Website URL
        </label>
        <div className="relative mb-4">
          <Globe
            size={15}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
          />
          <input
            autoFocus
            type="url"
            value={url}
            disabled={busy}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && url.trim() && submit()}
            placeholder="https://docs.example.com"
            className="w-full rounded-lg border border-line bg-canvas py-2 pl-9 pr-3 text-sm text-ink placeholder:text-faint focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand-ring disabled:opacity-60"
          />
        </div>

        <div className="mb-4 grid grid-cols-2 gap-2">
          {(
            [
              ["page", "Single page", "Just this URL"],
              ["site", "Whole site", "Follow sitemap or links"],
            ] as const
          ).map(([value, label, hint]) => (
            <button
              key={value}
              disabled={busy}
              onClick={() => setMode(value)}
              className={cn(
                "rounded-lg border p-3 text-left transition-colors disabled:opacity-60",
                mode === value
                  ? "border-brand bg-brand-soft"
                  : "border-line hover:bg-canvas",
              )}
            >
              <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
                <Layers size={13} />
                {label}
              </span>
              <span className="mt-0.5 block text-xs text-muted">{hint}</span>
            </button>
          ))}
        </div>

        {mode === "site" && (
          <label className="mb-4 block">
            <span className="mb-1.5 block text-xs font-medium text-body">
              Max pages — {maxPages}
            </span>
            <input
              type="range"
              min={1}
              max={200}
              value={maxPages}
              disabled={busy}
              onChange={(e) => setMaxPages(Number(e.target.value))}
              className="w-full accent-brand"
            />
          </label>
        )}

        {error != null && (
          <div className="mb-4">
            <ErrorNote error={error} />
          </div>
        )}

        {job && (
          <div className="mb-4 rounded-lg border border-line bg-canvas p-3">
            <div className="mb-2 flex items-center justify-between text-xs">
              <span className="font-medium text-body">
                {job.phase || job.status}
              </span>
              <span className="text-muted">{job.message}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-line">
              <div
                className="h-full rounded-full bg-brand transition-all duration-300"
                style={{ width: `${job.percent ?? 8}%` }}
              />
            </div>
            {job.error && (
              <p className="mt-2 text-xs text-bad">{job.error}</p>
            )}
          </div>
        )}

        <div className="flex justify-end gap-2">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={busy}
            disabled={!url.trim()}
          >
            {busy ? "Indexing…" : "Create & index"}
          </Button>
        </div>
      </div>
    </div>
  );
}
