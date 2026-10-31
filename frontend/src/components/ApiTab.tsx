import { useState } from "react";
import { useParams } from "react-router-dom";
import { Check, ChevronDown, ChevronRight, Copy, ExternalLink, Send } from "lucide-react";
import { API_BASE } from "../lib/api";
import { Badge, Button, Card, cn } from "./ui";

type Method = "GET" | "POST" | "DELETE";

interface Endpoint {
  method: Method;
  path: string;
  tag: string;
  description: string;
  body?: Record<string, unknown>;
  stream?: boolean;
}

const METHOD_TONE: Record<Method, string> = {
  GET: "bg-good-soft text-good border-good/25",
  POST: "bg-brand-soft text-brand border-brand-ring",
  DELETE: "bg-bad-soft text-bad border-bad/25",
};

function endpoints(ws: string): Endpoint[] {
  return [
    { method: "GET", path: "/health", tag: "Utility", description: "Liveness plus whether any LLM provider is usable." },
    { method: "GET", path: "/models", tag: "Utility", description: "Which providers are configured, and why one is not." },
    { method: "GET", path: "/workspaces", tag: "Workspaces", description: "List every indexed workspace." },
    {
      method: "POST",
      path: "/workspaces",
      tag: "Workspaces",
      description: "Create a workspace and start crawling it. Returns a job to follow.",
      body: { seed_url: "https://docs.example.com", mode: "page", start: true },
    },
    { method: "GET", path: `/workspaces/${ws}`, tag: "Workspaces", description: "Fetch one workspace." },
    { method: "DELETE", path: `/workspaces/${ws}`, tag: "Workspaces", description: "Delete a workspace, its pages and its collection." },
    { method: "POST", path: `/workspaces/${ws}/reindex?recrawl=false`, tag: "Workspaces", description: "Rebuild the index; optionally re-crawl first." },
    { method: "GET", path: `/workspaces/${ws}/documents?page=1&page_size=5`, tag: "Data", description: "Paginated indexed chunks with their source metadata." },
    { method: "GET", path: `/workspaces/${ws}/pages`, tag: "Data", description: "The crawl manifest: every page, with outlinks." },
    { method: "GET", path: `/workspaces/${ws}/graph`, tag: "Data", description: "Nodes and edges for the knowledge graph." },
    { method: "GET", path: `/workspaces/${ws}/queries`, tag: "Data", description: "Recent query history for this workspace." },
    {
      method: "POST",
      path: `/workspaces/${ws}/query`,
      tag: "Query",
      description: "Ask a question. Returns the answer plus its citations.",
      body: { prompt: "What is this site about?", engine: "auto", top_k: 5 },
    },
    {
      method: "POST",
      path: `/workspaces/${ws}/query/stream`,
      tag: "Query",
      description: "Same as /query but server-sent events: sources first, then tokens, then done.",
      body: { prompt: "What is this site about?", engine: "auto", top_k: 5 },
      stream: true,
    },
    {
      method: "POST",
      path: `/workspaces/${ws}/retrieval/compare`,
      tag: "Query",
      description: "Run all three retrieval strategies over one question and compare them.",
      body: { prompt: "installation steps", top_k: 5 },
    },
    { method: "GET", path: "/jobs", tag: "Jobs", description: "Recent background jobs." },
    { method: "GET", path: "/jobs/{job_id}/events", tag: "Jobs", description: "Live SSE progress for one job.", stream: true },
  ];
}

export default function ApiTab() {
  const { workspaceId } = useParams();
  const ws = workspaceId ?? "{workspace_id}";
  const list = endpoints(ws);

  const [open, setOpen] = useState<number | null>(null);
  const [responses, setResponses] = useState<Record<number, { status: number; body: string }>>({});
  const [busy, setBusy] = useState<Record<number, boolean>>({});
  const [copied, setCopied] = useState<string | null>(null);

  const copy = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(id);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      /* clipboard unavailable */
    }
  };

  const tryIt = async (ep: Endpoint, i: number) => {
    if (ep.path.includes("{job_id}")) return;
    setBusy((b) => ({ ...b, [i]: true }));
    try {
      const res = await fetch(`${API_BASE}${ep.path}`, {
        method: ep.method,
        ...(ep.body
          ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(ep.body) }
          : {}),
      });
      const text = await res.text();
      let pretty = text;
      if (!ep.stream) {
        try {
          pretty = JSON.stringify(JSON.parse(text), null, 2);
        } catch {
          /* leave as-is */
        }
      }
      setResponses((r) => ({ ...r, [i]: { status: res.status, body: pretty.slice(0, 4000) } }));
    } catch (err) {
      setResponses((r) => ({
        ...r,
        [i]: { status: 0, body: err instanceof Error ? err.message : String(err) },
      }));
    } finally {
      setBusy((b) => ({ ...b, [i]: false }));
    }
  };

  const curlFor = (ep: Endpoint) =>
    [
      `curl ${ep.stream ? "-N " : ""}-X ${ep.method} "${API_BASE || "http://localhost:8000"}${ep.path}"`,
      ep.body ? `  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(ep.body)}'` : "",
    ]
      .filter(Boolean)
      .join(" \\\n");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">API</h1>
          <p className="mt-1 text-sm text-muted">
            Every endpoint, runnable against the live server.
          </p>
        </div>
        <a
          href={`${API_BASE || "http://localhost:8000"}/docs`}
          target="_blank"
          rel="noreferrer"
        >
          <Button>
            OpenAPI docs <ExternalLink size={13} />
          </Button>
        </a>
      </div>

      <div className="space-y-2">
        {list.map((ep, i) => {
          const isOpen = open === i;
          const res = responses[i];
          return (
            <Card key={ep.path + ep.method} className="overflow-hidden">
              <button
                onClick={() => setOpen(isOpen ? null : i)}
                aria-expanded={isOpen}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-canvas"
              >
                {isOpen ? (
                  <ChevronDown size={14} className="shrink-0 text-faint" />
                ) : (
                  <ChevronRight size={14} className="shrink-0 text-faint" />
                )}
                <span
                  className={cn(
                    "w-16 shrink-0 rounded border px-1.5 py-0.5 text-center font-mono text-[10px] font-semibold",
                    METHOD_TONE[ep.method],
                  )}
                >
                  {ep.method}
                </span>
                <code className="truncate font-mono text-xs text-ink">{ep.path}</code>
                {ep.stream && <Badge tone="brand">SSE</Badge>}
                <span className="ml-auto hidden shrink-0 text-[11px] text-faint sm:block">
                  {ep.tag}
                </span>
              </button>

              {isOpen && (
                <div className="space-y-3 border-t border-line p-3">
                  <p className="text-xs text-muted">{ep.description}</p>

                  <div className="relative">
                    <pre className="overflow-x-auto rounded-lg bg-canvas p-3 font-mono text-[11px] leading-relaxed text-body">
                      {curlFor(ep)}
                    </pre>
                    <button
                      onClick={() => copy(curlFor(ep), String(i))}
                      className="absolute right-2 top-2 rounded p-1 text-faint hover:bg-surface hover:text-ink"
                      aria-label="Copy curl command"
                    >
                      {copied === String(i) ? <Check size={13} /> : <Copy size={13} />}
                    </button>
                  </div>

                  <Button
                    onClick={() => tryIt(ep, i)}
                    loading={busy[i]}
                    disabled={ep.path.includes("{job_id}")}
                  >
                    <Send size={13} />
                    {ep.path.includes("{job_id}") ? "Needs a job id" : "Try it"}
                  </Button>

                  {res && (
                    <div>
                      <div className="mb-1 flex items-center gap-2 text-[11px]">
                        <Badge tone={res.status >= 200 && res.status < 300 ? "good" : "bad"}>
                          {res.status || "network error"}
                        </Badge>
                      </div>
                      <pre className="max-h-72 overflow-auto rounded-lg bg-canvas p-3 font-mono text-[11px] leading-relaxed text-body">
                        {res.body}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </div>
  );
}
