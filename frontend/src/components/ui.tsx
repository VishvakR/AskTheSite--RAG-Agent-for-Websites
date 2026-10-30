import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand text-white hover:bg-brand-hover disabled:hover:bg-brand shadow-sm",
  secondary:
    "border border-line bg-surface text-body hover:bg-canvas hover:text-ink",
  ghost: "text-muted hover:bg-canvas hover:text-ink",
  danger: "border border-line text-bad hover:bg-bad-soft",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

export function Button({
  variant = "secondary",
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg px-3 py-2 text-sm font-medium",
        "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-ring",
        "disabled:cursor-not-allowed disabled:opacity-55",
        VARIANTS[variant],
        className,
      )}
    >
      {loading && <Spinner className="h-3.5 w-3.5" />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cn(
        "inline-block animate-spin rounded-full border-2 border-current border-t-transparent",
        className ?? "h-4 w-4",
      )}
    />
  );
}

export function Card({
  className,
  children,
  ...rest
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      {...rest}
      className={cn(
        "rounded-xl border border-line bg-surface shadow-sm",
        className,
      )}
    >
      {children}
    </div>
  );
}

type Tone = "neutral" | "good" | "warn" | "bad" | "brand";

const TONES: Record<Tone, string> = {
  neutral: "bg-canvas text-muted border-line",
  good: "bg-good-soft text-good border-good/25",
  warn: "bg-warn-soft text-warn border-warn/25",
  bad: "bg-bad-soft text-bad border-bad/25",
  brand: "bg-brand-soft text-brand border-brand-ring",
};

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-16 text-center">
      {icon && <div className="text-faint">{icon}</div>}
      <p className="text-sm font-medium text-body">{title}</p>
      {hint && <p className="max-w-sm text-xs text-muted">{hint}</p>}
      {action}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  const message =
    error instanceof Error ? error.message : String(error ?? "Unknown error");
  return (
    <div className="rounded-lg border border-bad/25 bg-bad-soft px-4 py-3 text-sm text-bad">
      {message}
    </div>
  );
}

/** Horizontal score bar, 0-1, tinted per retrieval strategy. */
export function ScoreBar({
  score,
  tone = "brand",
}: {
  score: number;
  tone?: "vec" | "kw" | "rank" | "brand";
}) {
  const colors = {
    vec: "bg-vec",
    kw: "bg-kw",
    rank: "bg-rank",
    brand: "bg-brand",
  } as const;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-canvas">
        <div
          className={cn("h-full rounded-full transition-all", colors[tone])}
          style={{ width: `${Math.max(2, Math.min(100, score * 100))}%` }}
        />
      </div>
      <span className="w-10 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted">
        {score.toFixed(3)}
      </span>
    </div>
  );
}

export const STATUS_TONE: Record<string, Tone> = {
  ready: "good",
  succeeded: "good",
  crawling: "brand",
  indexing: "brand",
  running: "brand",
  queued: "neutral",
  empty: "neutral",
  failed: "bad",
  cancelled: "warn",
};
