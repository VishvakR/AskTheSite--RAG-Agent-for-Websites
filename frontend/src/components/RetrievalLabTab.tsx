import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { FlaskConical, Link2, Search, Zap } from "lucide-react";
import { api } from "../lib/api";
import type { CompareResponse, Citation, Engine } from "../lib/types";
import { Badge, Button, Card, EmptyState, ErrorNote, ScoreBar, cn } from "./ui";

const COLUMNS: {
  engine: Engine;
  label: string;
  tone: "vec" | "kw" | "rank";
  blurb: string;
}[] = [
  {
    engine: "auto",
    label: "Vector",
    tone: "vec",
    blurb: "Cosine similarity over embeddings — finds meaning, misses exact terms.",
  },
  {
    engine: "bm25",
    label: "BM25",
    tone: "kw",
    blurb: "Keyword scoring — nails exact terms, blind to synonyms.",
  },
  {
    engine: "rerank",
    label: "Rerank",
    tone: "rank",
    blurb: "Both pools rescored by a cross-encoder — best quality, slowest.",
  },
];

const DOT: Record<string, string> = {
  vec: "bg-vec",
  kw: "bg-kw",
  rank: "bg-rank",
};

function chunkKey(c: Citation) {
  return `${c.page_id}:${c.chunk_index}`;
}

export default function RetrievalLabTab() {
  const { workspaceId } = useParams();
  const [prompt, setPrompt] = useState("");
  const [topK, setTopK] = useState(5);

  const run = useMutation({
    mutationFn: (q: string) => api.compare(workspaceId!, q, topK),
  });
  const data: CompareResponse | undefined = run.data;

  // A chunk found by more than one strategy is the interesting signal.
  const counts = new Map<string, number>();
  if (data) {
    for (const res of Object.values(data.strategies)) {
      for (const key of new Set(res.results.map(chunkKey))) {
        counts.set(key, (counts.get(key) ?? 0) + 1);
      }
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-lg font-semibold text-ink">
          <FlaskConical size={18} className="text-brand" />
          Retrieval Lab
        </h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Run one question through all three retrieval strategies at once and see
          exactly which chunks each one surfaces, with comparable relevance
          scores. This is the step most RAG apps hide.
        </p>
      </div>

      <Card className="p-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search
              size={15}
              className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
            />
            <input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) =>
                e.key === "Enter" && prompt.trim() && run.mutate(prompt.trim())
              }
              placeholder="Ask something — e.g. how do I configure the crawler?"
              className="w-full rounded-lg border border-line bg-canvas py-2 pl-9 pr-3 text-sm text-ink placeholder:text-faint focus:border-brand focus:outline-none focus:ring-1 focus:ring-brand-ring"
            />
          </div>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            top-k
            <input
              type="number"
              min={1}
              max={20}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              className="w-14 rounded border border-line bg-canvas px-2 py-1.5 text-center text-ink focus:border-brand focus:outline-none"
            />
          </label>
          <Button
            variant="primary"
            loading={run.isPending}
            disabled={!prompt.trim()}
            onClick={() => run.mutate(prompt.trim())}
          >
            Compare
          </Button>
        </div>
      </Card>

      {run.isError && <ErrorNote error={run.error} />}

      {!data && !run.isPending && (
        <Card>
          <EmptyState
            icon={<FlaskConical size={34} strokeWidth={1.2} />}
            title="Nothing compared yet"
            hint="Enter a question above. You'll get three ranked lists side by side, with chunks that more than one strategy agrees on highlighted."
          />
        </Card>
      )}

      {data && (
        <>
          <Card className="p-4">
            <h2 className="mb-3 flex items-center gap-1.5 text-sm font-medium text-ink">
              <Link2 size={14} />
              Agreement between strategies
            </h2>
            <div className="grid gap-3 sm:grid-cols-3">
              {Object.entries(data.overlap.pairwise).map(([pair, v]) => {
                const [a, b] = pair.split("|");
                return (
                  <div
                    key={pair}
                    className="rounded-lg border border-line bg-canvas p-3"
                  >
                    <div className="flex items-baseline justify-between">
                      <span className="text-xs text-muted">
                        {a} ↔ {b}
                      </span>
                      <span className="font-mono text-sm font-semibold text-ink">
                        {(v.jaccard * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line">
                      <div
                        className="h-full rounded-full bg-brand"
                        style={{ width: `${v.jaccard * 100}%` }}
                      />
                    </div>
                    <p className="mt-1.5 text-[11px] text-faint">
                      {v.shared_count} chunk{v.shared_count === 1 ? "" : "s"} in
                      common
                    </p>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-xs text-muted">
              Low overlap between Vector and BM25 is normal — they look for
              different things. Rerank draws from both pools, so it usually
              overlaps each of them more than they overlap each other.
            </p>
          </Card>

          <div className="grid gap-4 lg:grid-cols-3">
            {COLUMNS.map(({ engine, label, tone, blurb }) => {
              const res = data.strategies[engine];
              return (
                <Card key={engine} className="flex flex-col">
                  <div className="border-b border-line p-3">
                    <div className="flex items-center justify-between">
                      <span className="flex items-center gap-2 text-sm font-semibold text-ink">
                        <span className={cn("h-2 w-2 rounded-full", DOT[tone])} />
                        {label}
                      </span>
                      <Badge tone="neutral">
                        <Zap size={10} />
                        {res.elapsed_ms < 1 ? "<1" : res.elapsed_ms}ms
                      </Badge>
                    </div>
                    <p className="mt-1 text-[11px] leading-snug text-muted">
                      {blurb}
                    </p>
                  </div>

                  {res.error ? (
                    <div className="p-3">
                      <ErrorNote error={res.error} />
                    </div>
                  ) : res.results.length === 0 ? (
                    <EmptyState title="No matches" />
                  ) : (
                    <ol className="divide-y divide-line">
                      {res.results.map((c) => {
                        const shared = (counts.get(chunkKey(c)) ?? 0) > 1;
                        return (
                          <li
                            key={`${c.page_id}-${c.chunk_index}`}
                            className={cn(
                              "space-y-1.5 p-3",
                              shared && "bg-brand-soft/40",
                            )}
                          >
                            <div className="flex items-center gap-2">
                              <span className="font-mono text-[11px] text-faint">
                                #{c.rank}
                              </span>
                              <span className="truncate text-xs font-medium text-ink">
                                {c.page_title || c.source_url}
                              </span>
                              {shared && (
                                <span
                                  title="Also retrieved by another strategy"
                                  className="ml-auto shrink-0 rounded-full border border-brand-ring bg-brand-soft px-1.5 text-[10px] font-medium text-brand"
                                >
                                  shared
                                </span>
                              )}
                            </div>
                            {c.heading && (
                              <p className="truncate text-[11px] text-muted">
                                {c.heading}
                              </p>
                            )}
                            <ScoreBar score={c.score} tone={tone} />
                            <p className="line-clamp-3 text-[11px] leading-relaxed text-body">
                              {c.snippet}
                            </p>
                          </li>
                        );
                      })}
                    </ol>
                  )}
                </Card>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
