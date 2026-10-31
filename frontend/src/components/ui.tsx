import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-brand text-white dark:text-canvas hover:bg-brand-hover disabled:hover:bg-brand",
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
        "inline-flex items-center justify-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium",
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

/** Square, label-less button for toolbars; always pass an aria-label. */
export function IconButton({
  className,
  active,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { active?: boolean }) {
  return (
    <button
      {...rest}
      className={cn(
        "grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted transition-colors",
        "hover:bg-canvas hover:text-ink disabled:opacity-40",
        active && "bg-canvas text-ink",
        className,
      )}
    />
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded border border-line bg-surface px-1.5 py-px font-sans text-[11px] text-muted">
      {children}
    </kbd>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-40",
        checked ? "bg-brand" : "bg-line-strong",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
          checked && "translate-x-4",
        )}
      />
    </button>
  );
}

/**
 * Click-to-open floating panel anchored to its trigger. Closes on outside
 * click and Escape; the trigger keeps focus semantics via aria-expanded.
 */
export function Popover({
  trigger,
  children,
  align = "start",
  side = "bottom",
  className,
  open: controlled,
  onOpenChange,
}: {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  children: ReactNode | ((close: () => void) => ReactNode);
  align?: "start" | "end";
  side?: "top" | "bottom";
  className?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [inner, setInner] = useState(false);
  const open = controlled ?? inner;
  const setOpen = (value: boolean) => {
    setInner(value);
    onOpenChange?.(value);
  };
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  });

  const close = () => setOpen(false);
  return (
    <div ref={ref} className="relative">
      {trigger({ open, toggle: () => setOpen(!open) })}
      {open && (
        <div
          className={cn(
            "absolute z-40 min-w-56 rounded-xl border border-line bg-raised p-1.5 shadow-[0_12px_32px_-12px_rgb(15_20_30/0.28)]",
            side === "bottom" ? "top-full mt-1.5" : "bottom-full mb-1.5",
            align === "start" ? "left-0" : "right-0",
            className,
          )}
        >
          {typeof children === "function" ? children(close) : children}
        </div>
      )}
    </div>
  );
}

export function MenuItem({
  className,
  danger,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { danger?: boolean }) {
  return (
    <button
      {...rest}
      className={cn(
        "flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-sm transition-colors",
        danger ? "text-bad hover:bg-bad-soft" : "text-body hover:bg-canvas hover:text-ink",
        "disabled:opacity-40",
        className,
      )}
    />
  );
}
