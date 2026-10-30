import { useEffect, useState } from "react";
import {
  AlertCircle,
  Check,
  ChevronRight,
  Copy,
  Pencil,
  RotateCcw,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { api } from "../../lib/api";
import type { TurnModel } from "../../lib/chat";
import { describeTool } from "../../lib/tools";
import type { Grounding, ToolStep } from "../../lib/types";
import { Spinner, cn } from "../ui";
import { Answer } from "./Answer";

// ── tool activity ─────────────────────────────────────────────────────────

function resultSummary(step: ToolStep): string | null {
  const text = step.preview ?? step.result ?? "";
  if (step.is_error) return text.replace(/^Error:\s*/, "");
  if (step.name === "search_site") {
    const n = (text.match(/^\[\d+\]/gm) ?? []).length;
    if (n) return `${n} passage${n === 1 ? "" : "s"}`;
    if (text.startsWith("No passages")) return "nothing found";
  }
  return null;
}

function ToolRow({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const { icon: Icon, text } = describeTool(step);
  const summary = resultSummary(step);
  const running = !step.done;
  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="group flex w-full items-center gap-2.5 rounded-md py-1 text-left text-[13.5px] text-muted hover:text-ink"
      >
        <span className="grid h-5 w-5 shrink-0 place-items-center">
          {running ? (
            <Spinner className="h-3 w-3 text-brand" />
          ) : step.is_error ? (
            <AlertCircle size={14} className="text-bad" />
          ) : (
            <Icon size={14} />
          )}
        </span>
        <span className={cn("min-w-0 truncate", running && "text-body")}>{text}</span>
        {summary && <span className={cn("shrink-0", step.is_error ? "text-bad" : "text-faint")}>{summary}</span>}
        {step.elapsed_ms != null && <span className="shrink-0 text-faint">{step.elapsed_ms} ms</span>}
        <ChevronRight size={13} className={cn("ml-auto shrink-0 text-faint transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="mb-2 ml-7 space-y-2 rounded-md border border-line bg-canvas p-2.5 text-xs">
          <pre className="overflow-x-auto font-mono text-[11.5px] text-body">{JSON.stringify(step.arguments, null, 2)}</pre>
          {(step.preview ?? step.result) && (
            <pre className="max-h-48 overflow-auto border-t border-line pt-2 font-mono text-[11.5px] whitespace-pre-wrap text-muted">
              {step.preview ?? step.result}
            </pre>
          )}
        </div>
      )}
    </li>
  );
}

// ── reasoning ─────────────────────────────────────────────────────────────

function useTicker(active: boolean) {
  const [, force] = useState(0);
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => force((n) => n + 1), 200);
    return () => clearInterval(id);
  }, [active]);
}

function Reasoning({ text, ms, live }: { text: string; ms?: number; live: boolean }) {
  const [open, setOpen] = useState(false);
  const [started] = useState(() => performance.now());
  useTicker(live && ms === undefined);
  const seconds = ((ms ?? performance.now() - started) / 1000).toFixed(1);
  const label = live && ms === undefined ? `Reasoning… ${seconds}s` : ms !== undefined ? `Reasoned for ${seconds}s` : "Reasoning";
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-1.5 py-1 text-[13.5px] text-muted hover:text-ink"
      >
        <ChevronRight size={13} className={cn("transition-transform", open && "rotate-90")} />
        {label}
      </button>
      {open && (
        <div className="mt-1 mb-2 max-h-80 overflow-y-auto border-l-2 border-line pl-4 text-[13.5px] leading-relaxed whitespace-pre-wrap text-muted">
          {text}
        </div>
      )}
    </div>
  );
}

// ── grounding ─────────────────────────────────────────────────────────────

/**
 * How much of the answer is backed by a cited source: one tick per claim,
 * highlighted when a source stands behind it.
 */
function GroundingMeter({ grounding, onShowSources }: { grounding: Grounding; onShowSources: () => void }) {
  const [open, setOpen] = useState(false);
  if (grounding.score == null || grounding.sentences === 0) return null;
  const total = grounding.sentences;
  const cells = Math.min(total, 16);
  const filled = Math.round((grounding.supported / total) * cells);
  const unsupported = total - grounding.supported;
  const label =
    unsupported === 0
      ? `Every claim cites a source`
      : `${grounding.supported} of ${total} claims cite a source`;
  const hasDetail = grounding.uncited.length > 0 || grounding.invalid_markers.length > 0;
  return (
    <div className="text-[13px]">
      <button
        type="button"
        disabled={!hasDetail}
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex items-center gap-2.5 text-muted enabled:hover:text-ink"
        title="Checks each sentence of the answer for a citation to a retrieved source"
      >
        <span className="flex gap-[3px]" aria-hidden>
          {Array.from({ length: cells }, (_, i) => (
            <span key={i} className={cn("h-3 w-1.5 rounded-[2px]", i < filled ? "bg-mark" : "bg-line-strong")} />
          ))}
        </span>
        <span>{label}</span>
        {hasDetail && <ChevronRight size={13} className={cn("transition-transform", open && "rotate-90")} />}
      </button>
      {open && (
        <div className="mt-2 space-y-2 border-l-2 border-mark pl-3 text-body">
          {grounding.uncited.length > 0 && (
            <>
              <p className="text-muted">Worth checking before you rely on them:</p>
              <ul className="space-y-1">
                {grounding.uncited.map((s, i) => (
                  <li key={i} className="font-serif text-[14.5px] text-ink">{s}</li>
                ))}
              </ul>
            </>
          )}
          {grounding.invalid_markers.length > 0 && (
            <p className="text-bad">
              Cites {grounding.invalid_markers.map((m) => `[${m}]`).join(", ")}, which {grounding.invalid_markers.length === 1 ? "isn’t" : "aren’t"} among the retrieved sources.
            </p>
          )}
          <button type="button" onClick={onShowSources} className="text-brand hover:underline">
            Open the sources
          </button>
        </div>
      )}
    </div>
  );
}

// ── turn ──────────────────────────────────────────────────────────────────

const PHASE: Record<TurnModel["phase"], string> = {
  searching: "Searching your sites…",
  thinking: "Thinking it through…",
  writing: "Writing…",
  done: "",
};

function seconds(ms?: number | null) {
  return ms == null ? null : `${(ms / 1000).toFixed(1)} s`;
}

export function TurnView({
  turn,
  isLast,
  busy,
  activeMarker,
  onPickCitation,
  onOpenInspector,
  onRetry,
  onEdit,
  onFollowUp,
  onDismissError,
}: {
  turn: TurnModel;
  isLast: boolean;
  busy: boolean;
  activeMarker?: number | null;
  onPickCitation: (turnKey: string, marker: number) => void;
  onOpenInspector: (turnKey: string) => void;
  onRetry: (turnId: string) => void;
  onEdit: (turnId: string, prompt: string) => void;
  onFollowUp: (question: string) => void;
  onDismissError?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(turn.question);
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState(turn.feedback);

  const copy = async () => {
    await navigator.clipboard.writeText(turn.answer);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const rate = (value: -1 | 1) => {
    if (!turn.messageId) return;
    const next = feedback === value ? 0 : value;
    setFeedback(next);
    api.feedback(turn.messageId, next).catch(() => setFeedback(feedback));
  };

  const finished = !turn.streaming && !turn.error;

  return (
    <article className="group/turn scroll-mt-24" aria-busy={turn.streaming}>
      {editing ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim() && turn.turnId) {
              setEditing(false);
              onEdit(turn.turnId, draft.trim());
            }
          }}
          className="rounded-xl border border-brand-ring bg-surface p-2"
        >
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                e.currentTarget.form?.requestSubmit();
              }
              if (e.key === "Escape") setEditing(false);
            }}
            rows={2}
            className="w-full resize-none bg-transparent px-2 py-1 text-[17px] font-semibold text-ink focus:outline-none"
          />
          <div className="flex justify-end gap-2 px-1">
            <button type="button" onClick={() => setEditing(false)} className="rounded-md px-2.5 py-1 text-sm text-muted hover:bg-canvas">
              Cancel
            </button>
            <button type="submit" className="rounded-md bg-brand px-2.5 py-1 text-sm font-medium text-white dark:text-canvas">
              Ask again
            </button>
          </div>
        </form>
      ) : (
        <div className="flex items-start gap-3">
          <h2 className="min-w-0 flex-1 text-[17px] leading-snug font-semibold text-ink">{turn.question}</h2>
          {finished && turn.turnId && !busy && (
            <button
              type="button"
              onClick={() => {
                setDraft(turn.question);
                setEditing(true);
              }}
              aria-label="Edit question"
              className="mt-0.5 rounded-md p-1 text-faint opacity-0 group-hover/turn:opacity-100 hover:text-ink focus-visible:opacity-100"
            >
              <Pencil size={14} />
            </button>
          )}
        </div>
      )}

      <div className="mt-3 space-y-1">
        {turn.notices.map((n, i) => (
          <p key={i} className="text-[13px] text-warn">{n}</p>
        ))}
        {turn.reasoning && <Reasoning text={turn.reasoning} ms={turn.reasoningMs} live={turn.streaming} />}
        {turn.tools.length > 0 && (
          <ul className="py-0.5">
            {turn.tools.map((t) => (
              <ToolRow key={t.id} step={t} />
            ))}
          </ul>
        )}
      </div>

      <div className="mt-3">
        {turn.answer ? (
          <Answer
            text={turn.answer}
            citations={turn.citations}
            activeMarker={activeMarker}
            onPick={(m) => onPickCitation(turn.key, m)}
            streaming={turn.streaming && turn.phase === "writing"}
          />
        ) : turn.streaming ? (
          <p className="flex items-center gap-2 text-[14px] text-muted">
            <Spinner className="h-3.5 w-3.5" />
            {PHASE[turn.phase] || "Working…"}
          </p>
        ) : null}
      </div>

      {turn.error && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-bad/25 bg-bad-soft px-3 py-2 text-sm text-bad">
          <AlertCircle size={15} className="mt-0.5 shrink-0" />
          <p className="flex-1">{turn.error}</p>
          {onDismissError && (
            <button type="button" onClick={onDismissError} className="text-bad/80 hover:text-bad">
              Dismiss
            </button>
          )}
        </div>
      )}

      {finished && turn.answer && (
        <div className="mt-4 space-y-3">
          {turn.grounding && <GroundingMeter grounding={turn.grounding} onShowSources={() => onOpenInspector(turn.key)} />}
          <div className="flex flex-wrap items-center gap-x-1 gap-y-2 text-[13px] text-faint">
            <ActionButton label={copied ? "Copied" : "Copy answer"} onClick={copy}>
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </ActionButton>
            {isLast && turn.turnId && (
              <ActionButton label="Ask again" onClick={() => onRetry(turn.turnId!)} disabled={busy}>
                <RotateCcw size={14} />
              </ActionButton>
            )}
            <ActionButton label="Good answer" onClick={() => rate(1)} pressed={feedback === 1}>
              <ThumbsUp size={14} />
            </ActionButton>
            <ActionButton label="Bad answer" onClick={() => rate(-1)} pressed={feedback === -1}>
              <ThumbsDown size={14} />
            </ActionButton>
            {turn.citations.length > 0 && (
              <button
                type="button"
                onClick={() => onOpenInspector(turn.key)}
                className="ml-1 rounded-md px-2 py-1 text-muted hover:bg-canvas hover:text-ink"
              >
                {turn.citations.length} source{turn.citations.length === 1 ? "" : "s"}
              </button>
            )}
            <span className="ml-auto flex gap-3">
              {turn.model && <span>{turn.model}</span>}
              {seconds(turn.elapsedMs) && <span>{seconds(turn.elapsedMs)}</span>}
              {turn.cancelled && <span className="text-warn">stopped</span>}
            </span>
          </div>
        </div>
      )}

      {isLast && turn.followups.length > 0 && !busy && (
        <div className="mt-5">
          <p className="mb-1.5 text-[13px] text-muted">You could ask next</p>
          <ul className="space-y-0.5">
            {turn.followups.map((q) => (
              <li key={q}>
                <button
                  type="button"
                  onClick={() => onFollowUp(q)}
                  className="w-full rounded-md border-l-2 border-line py-1 pl-3 text-left text-[14.5px] text-body hover:border-brand hover:bg-surface hover:text-ink"
                >
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}

function ActionButton({
  label,
  onClick,
  pressed,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "grid h-7 w-7 place-items-center rounded-md hover:bg-canvas hover:text-ink disabled:opacity-40",
        pressed && "bg-brand-soft text-brand",
      )}
    >
      {children}
    </button>
  );
}
