import { useEffect, useRef } from "react";
import { ExternalLink, X } from "lucide-react";
import type { TurnModel } from "../../lib/chat";
import { cleanSnippet } from "../../lib/citations";
import type { TraceEntry, Usage } from "../../lib/types";
import { IconButton, cn } from "../ui";
import { describeTool } from "../../lib/tools";

export type InspectorTab = "sources" | "steps" | "usage";

function hostPath(url: string) {
  try {
    const u = new URL(url);
    return `${u.host}${u.pathname === "/" ? "" : u.pathname}`;
  } catch {
    return url;
  }
}

function Sources({ turn, activeMarker }: { turn: TurnModel; activeMarker?: number | null }) {
  const refs = useRef(new Map<number, HTMLLIElement>());
  useEffect(() => {
    if (activeMarker != null) refs.current.get(activeMarker)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeMarker]);

  if (!turn.citations.length) {
    return <p className="px-5 py-6 text-sm text-muted">This answer didn’t retrieve any passages.</p>;
  }
  const cited = new Set((turn.answer.match(/\[(\d+)\]/g) ?? []).map((m) => Number(m.slice(1, -1))));
  return (
    <ol className="divide-y divide-line">
      {turn.citations.map((c) => (
        <li
          key={c.marker}
          ref={(el) => {
            if (el) refs.current.set(c.marker, el);
          }}
          className={cn("px-5 py-4", activeMarker === c.marker && "bg-mark-soft/50")}
        >
          <div className="flex items-start gap-2.5">
            <span className="cite !m-0 !align-baseline">{c.marker}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] leading-snug font-semibold text-ink">{c.page_title || hostPath(c.source_url)}</p>
              {c.heading && <p className="text-[13px] text-muted">{c.heading}</p>}
            </div>
            <a
              href={c.source_url}
              target="_blank"
              rel="noreferrer"
              aria-label="Open the page"
              className="mt-0.5 text-faint hover:text-brand"
            >
              <ExternalLink size={14} />
            </a>
          </div>
          <p className="mt-2 font-serif text-[14.5px] leading-relaxed text-body">{cleanSnippet(c.snippet)}</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-faint">
            <span className="truncate">{hostPath(c.source_url)}</span>
            {c.workspace_name && <span>{c.workspace_name}</span>}
            <span title="Relevance, 0 to 1">relevance {c.score.toFixed(2)}</span>
            {!cited.has(c.marker) && <span className="text-warn">not cited</span>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function stepLabel(t: TraceEntry): string {
  if (t.kind === "retrieve") return `Retrieved ${t.hits ?? 0} passages (${t.engine})`;
  if (t.kind === "tool") return describeTool({ name: t.name ?? "", arguments: {} }).text.replace(/ “”$/, "");
  if (t.kind === "cancelled") return "Stopped";
  const calls = t.tool_calls ? `, asked for ${t.tool_calls} tool${t.tool_calls === 1 ? "" : "s"}` : "";
  return `Model call ${t.step ?? ""}${calls}`;
}

function Steps({ trace }: { trace: TraceEntry[] }) {
  if (!trace.length) return <p className="px-5 py-6 text-sm text-muted">Steps appear once the answer is saved.</p>;
  const longest = Math.max(1, ...trace.map((t) => t.elapsed_ms ?? 0));
  return (
    <ol className="space-y-3 px-5 py-4">
      {trace.map((t, i) => (
        <li key={i} className="text-[13px]">
          <div className="flex justify-between gap-3">
            <span className={cn("truncate", t.is_error ? "text-bad" : t.kind === "model" ? "text-ink" : "text-body")}>
              {stepLabel(t)}
            </span>
            {t.elapsed_ms != null && <span className="shrink-0 text-faint">{t.elapsed_ms} ms</span>}
          </div>
          {t.elapsed_ms != null && (
            <div className="mt-1 h-1 rounded-full bg-canvas">
              <div
                className={cn("h-full rounded-full", t.kind === "model" ? "bg-brand" : "bg-line-strong")}
                style={{ width: `${Math.max(2, ((t.elapsed_ms ?? 0) / longest) * 100)}%` }}
              />
            </div>
          )}
          {t.kind === "model" && (t.input_tokens || t.output_tokens) ? (
            <p className="mt-1 text-[12px] text-faint">
              {t.input_tokens?.toLocaleString()} in, {t.output_tokens?.toLocaleString()} out
            </p>
          ) : null}
        </li>
      ))}
    </ol>
  );
}

function UsagePanel({ turn, session }: { turn?: Usage | null; session?: Usage | null }) {
  const row = (label: string, u?: Usage | null) => (
    <div className="grid grid-cols-[1fr_auto] gap-y-1.5 text-[13.5px]">
      <span className="col-span-2 mb-1 font-semibold text-ink">{label}</span>
      <span className="text-muted">Prompt tokens</span>
      <span className="text-right tabular-nums">{(u?.input_tokens ?? 0).toLocaleString()}</span>
      <span className="text-muted">Answer tokens</span>
      <span className="text-right tabular-nums">{(u?.output_tokens ?? 0).toLocaleString()}</span>
      <span className="text-muted">Read from cache</span>
      <span className="text-right tabular-nums">{(u?.cache_read_tokens ?? 0).toLocaleString()}</span>
    </div>
  );
  return (
    <div className="space-y-6 px-5 py-4">
      {row("This answer", turn)}
      {row("Whole chat", session)}
      <p className="text-[12.5px] text-faint">Local models report what Ollama counts; follow-up suggestions are included.</p>
    </div>
  );
}

export function Inspector({
  turn,
  tab,
  onTab,
  activeMarker,
  sessionUsage,
  onClose,
}: {
  turn: TurnModel;
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  activeMarker?: number | null;
  sessionUsage?: Usage | null;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const tabs: [InspectorTab, string][] = [
    ["sources", `Sources${turn.citations.length ? ` ${turn.citations.length}` : ""}`],
    ["steps", "Steps"],
    ["usage", "Usage"],
  ];

  return (
    <aside
      aria-label="Answer details"
      className="animate-slide-in fixed inset-y-0 right-0 z-40 flex w-full max-w-[26rem] flex-col border-l border-line bg-surface shadow-[-16px_0_40px_-24px_rgb(15_20_30/0.35)] xl:static xl:z-auto xl:h-svh xl:shadow-none"
    >
      <div className="flex items-start gap-3 border-b border-line px-5 pt-4">
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] text-muted">{turn.question}</p>
          <div className="mt-2 flex gap-4" role="tablist">
            {tabs.map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => onTab(key)}
                className={cn(
                  "-mb-px border-b-2 pb-2 text-[13.5px]",
                  tab === key ? "border-ink font-medium text-ink" : "border-transparent text-muted hover:text-ink",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <IconButton aria-label="Close details" onClick={onClose}>
          <X size={16} />
        </IconButton>
      </div>
      <div className="flex-1 overflow-y-auto">
        {tab === "sources" && <Sources turn={turn} activeMarker={activeMarker} />}
        {tab === "steps" && <Steps trace={turn.trace} />}
        {tab === "usage" && <UsagePanel turn={turn.usage} session={sessionUsage} />}
      </div>
    </aside>
  );
}
