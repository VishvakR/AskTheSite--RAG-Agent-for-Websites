import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ArrowUp,
  ExternalLink,
  MessageSquare,
  Square,
  Trash2,
} from "lucide-react";
import { API_BASE } from "../lib/api";
import { streamSse } from "../lib/sse";
import type { Citation, Engine } from "../lib/types";
import { Badge, Button, Card, EmptyState, ErrorNote, Spinner, cn } from "./ui";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  engine?: Engine;
  elapsedMs?: number;
  model?: string;
  streaming?: boolean;
  error?: string;
}

const ENGINES: { value: Engine; label: string; hint: string }[] = [
  { value: "auto", label: "Vector", hint: "Cosine similarity search" },
  { value: "bm25", label: "BM25", hint: "Keyword search" },
  { value: "rerank", label: "Rerank", hint: "Hybrid + cross-encoder (slowest, best)" },
];

/**
 * Renders text with `[1]`-style markers turned into clickable citation chips.
 * The model is prompted to cite inline, so these markers map onto the
 * `sources` payload that arrives before the first token.
 */
function withCitations(
  node: React.ReactNode,
  citations: Citation[] | undefined,
  onPick: (c: Citation) => void,
): React.ReactNode {
  if (!citations?.length) return node;

  const render = (value: React.ReactNode, key: number): React.ReactNode => {
    if (typeof value !== "string") return value;
    const parts = value.split(/(\[\d+\])/g);
    return (
      <Fragment key={key}>
        {parts.map((part, i) => {
          const match = /^\[(\d+)\]$/.exec(part);
          if (!match) return part;
          const citation = citations.find((c) => c.marker === Number(match[1]));
          if (!citation) return part;
          return (
            <button
              key={i}
              onClick={() => onPick(citation)}
              title={`${citation.page_title} — ${citation.source_url}`}
              className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded border border-brand-ring bg-brand-soft px-1 align-super font-mono text-[10px] font-semibold text-brand hover:bg-brand hover:text-white"
            >
              {citation.marker}
            </button>
          );
        })}
      </Fragment>
    );
  };

  if (Array.isArray(node)) return node.map(render);
  return render(node, 0);
}

function SourceCard({
  citation,
  onPick,
}: {
  citation: Citation;
  onPick: (c: Citation) => void;
}) {
  return (
    <button
      onClick={() => onPick(citation)}
      className="w-full rounded-lg border border-line bg-canvas p-2.5 text-left transition-colors hover:border-brand-ring hover:bg-brand-soft"
    >
      <div className="flex items-center gap-2">
        <span className="grid h-4 min-w-4 place-items-center rounded border border-brand-ring bg-brand-soft px-1 font-mono text-[10px] font-semibold text-brand">
          {citation.marker}
        </span>
        <span className="truncate text-xs font-medium text-ink">
          {citation.page_title || citation.source_url}
        </span>
        <span className="ml-auto shrink-0 font-mono text-[10px] text-muted">
          {citation.score.toFixed(3)}
        </span>
      </div>
      {citation.heading && (
        <p className="mt-1 truncate text-[11px] text-muted">{citation.heading}</p>
      )}
    </button>
  );
}

export default function ChatTab() {
  const { workspaceId } = useParams();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [engine, setEngine] = useState<Engine>("auto");
  const [topK, setTopK] = useState(5);
  const [streaming, setStreaming] = useState(false);
  const [selected, setSelected] = useState<Citation | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
    setMessages((prev) =>
      prev.map((m) => (m.streaming ? { ...m, streaming: false } : m)),
    );
  }, []);

  const send = useCallback(async () => {
    const prompt = input.trim();
    if (!prompt || streaming || !workspaceId) return;

    const assistantId = crypto.randomUUID();
    setMessages((prev) => [
      ...prev,
      { id: crypto.randomUUID(), role: "user", content: prompt },
      { id: assistantId, role: "assistant", content: "", streaming: true },
    ]);
    setInput("");
    setStreaming(true);

    const ac = new AbortController();
    abortRef.current = ac;

    const patch = (fn: (m: Message) => Message) =>
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));

    try {
      for await (const msg of streamSse(
        `${API_BASE}/workspaces/${workspaceId}/query/stream`,
        {
          method: "POST",
          body: JSON.stringify({ prompt, engine, top_k: topK }),
        },
        ac.signal,
      )) {
        const data = msg.data as Record<string, unknown>;
        if (msg.event === "sources") {
          patch((m) => ({
            ...m,
            citations: (data.citations as Citation[]) ?? [],
            engine: data.engine as Engine,
          }));
        } else if (msg.event === "token") {
          patch((m) => ({ ...m, content: m.content + String(data.t ?? "") }));
        } else if (msg.event === "done") {
          patch((m) => ({
            ...m,
            streaming: false,
            elapsedMs: data.elapsed_ms as number,
            model: data.model as string,
          }));
        } else if (msg.event === "error") {
          patch((m) => ({
            ...m,
            streaming: false,
            error: String(data.message ?? "Generation failed"),
          }));
        }
      }
    } catch (err) {
      if (!ac.signal.aborted) {
        patch((m) => ({
          ...m,
          streaming: false,
          error: err instanceof Error ? err.message : String(err),
        }));
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }, [input, streaming, workspaceId, engine, topK]);

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="flex min-h-[calc(100svh-12rem)] flex-col">
        <div className="flex-1 space-y-5">
          {messages.length === 0 && (
            <Card>
              <EmptyState
                icon={<MessageSquare size={34} strokeWidth={1.2} />}
                title="Ask this site anything"
                hint="Answers are grounded in the crawled pages and cite their sources inline. Click any citation to see the exact chunk it came from."
              />
            </Card>
          )}

          {messages.map((message) =>
            message.role === "user" ? (
              <div key={message.id} className="flex justify-end">
                <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-brand px-4 py-2.5 text-sm text-white">
                  {message.content}
                </div>
              </div>
            ) : (
              <div key={message.id} className="animate-fade-rise space-y-2">
                {message.citations && message.citations.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] uppercase tracking-wide text-faint">
                      Sources
                    </span>
                    {message.citations.map((c) => (
                      <button
                        key={c.marker}
                        onClick={() => setSelected(c)}
                        className="max-w-[16rem] truncate rounded-full border border-line bg-canvas px-2 py-0.5 text-[11px] text-muted hover:border-brand-ring hover:text-brand"
                      >
                        [{c.marker}] {c.page_title || c.source_url}
                      </button>
                    ))}
                  </div>
                )}

                <Card className="px-4 py-3">
                  {message.content ? (
                    <div className="prose-sm max-w-none text-sm leading-relaxed text-body [&_a]:text-brand [&_code]:rounded [&_code]:bg-canvas [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[0.85em] [&_h1]:mt-3 [&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-ink [&_h2]:mt-3 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-ink [&_li]:my-0.5 [&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_p]:my-2 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-canvas [&_pre]:p-3 [&_strong]:text-ink [&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          p: ({ children }) => (
                            <p>{withCitations(children, message.citations, setSelected)}</p>
                          ),
                          li: ({ children }) => (
                            <li>{withCitations(children, message.citations, setSelected)}</li>
                          ),
                        }}
                      >
                        {message.content}
                      </ReactMarkdown>
                      {message.streaming && (
                        <span className="animate-caret ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 bg-brand" />
                      )}
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 py-1 text-sm text-muted">
                      <Spinner className="h-3.5 w-3.5" />
                      {message.citations
                        ? "Writing answer…"
                        : "Searching the index…"}
                    </div>
                  )}

                  {message.error && (
                    <div className="mt-2">
                      <ErrorNote error={message.error} />
                    </div>
                  )}

                  {!message.streaming && message.elapsedMs != null && (
                    <div className="mt-2.5 flex gap-3 border-t border-line pt-2 text-[11px] text-faint">
                      <span>{(message.elapsedMs / 1000).toFixed(1)}s</span>
                      {message.model && <span>{message.model}</span>}
                      {message.engine && <span>{message.engine}</span>}
                    </div>
                  )}
                </Card>
              </div>
            ),
          )}
          <div ref={endRef} />
        </div>

        <div className="sticky bottom-0 mt-4 bg-canvas pt-3">
          <Card className="p-2">
            <div className="flex items-end gap-2">
              <textarea
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder="Ask a question about this site…  (Enter to send)"
                className="max-h-40 min-h-[2.5rem] flex-1 resize-y bg-transparent px-2 py-2 text-sm text-ink placeholder:text-faint focus:outline-none"
              />
              {streaming ? (
                <Button variant="secondary" onClick={stop}>
                  <Square size={13} />
                  Stop
                </Button>
              ) : (
                <Button variant="primary" onClick={send} disabled={!input.trim()}>
                  <ArrowUp size={15} />
                </Button>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-line px-2 pt-2">
              <div className="flex gap-1">
                {ENGINES.map((e) => (
                  <button
                    key={e.value}
                    title={e.hint}
                    onClick={() => setEngine(e.value)}
                    className={cn(
                      "rounded-md px-2 py-1 text-xs transition-colors",
                      engine === e.value
                        ? "bg-brand-soft font-medium text-brand"
                        : "text-muted hover:bg-canvas",
                    )}
                  >
                    {e.label}
                  </button>
                ))}
              </div>
              <label className="ml-auto flex items-center gap-1.5 text-xs text-muted">
                top-k
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                  className="w-12 rounded border border-line bg-canvas px-1.5 py-0.5 text-center text-ink focus:border-brand focus:outline-none"
                />
              </label>
              {messages.length > 0 && (
                <Button variant="ghost" onClick={() => setMessages([])}>
                  <Trash2 size={13} />
                  Clear
                </Button>
              )}
            </div>
          </Card>
        </div>
      </div>

      <aside className="hidden lg:block">
        <div className="sticky top-32 space-y-2">
          <h3 className="text-xs font-medium uppercase tracking-wide text-faint">
            Source inspector
          </h3>
          {selected ? (
            <Card className="p-3">
              <div className="mb-2 flex items-start justify-between gap-2">
                <Badge tone="brand">[{selected.marker}]</Badge>
                <a
                  href={selected.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="flex items-center gap-1 text-[11px] text-brand hover:underline"
                >
                  Open <ExternalLink size={11} />
                </a>
              </div>
              <p className="text-sm font-medium text-ink">
                {selected.page_title}
              </p>
              {selected.heading && (
                <p className="mt-0.5 text-xs text-muted">{selected.heading}</p>
              )}
              <p className="mt-2 border-t border-line pt-2 text-xs leading-relaxed text-body">
                {selected.snippet}
              </p>
              <div className="mt-2 flex justify-between text-[11px] text-faint">
                <span>score {selected.score.toFixed(3)}</span>
                <span>chunk #{selected.chunk_index}</span>
              </div>
            </Card>
          ) : (
            <Card>
              <EmptyState
                title="No source selected"
                hint="Click a citation marker in an answer to inspect the exact chunk behind it."
              />
            </Card>
          )}

          {messages.at(-1)?.citations?.length ? (
            <div className="space-y-1.5 pt-2">
              <h3 className="text-xs font-medium uppercase tracking-wide text-faint">
                Retrieved for last answer
              </h3>
              {messages.at(-1)!.citations!.map((c) => (
                <SourceCard key={c.marker} citation={c} onPick={setSelected} />
              ))}
            </div>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
