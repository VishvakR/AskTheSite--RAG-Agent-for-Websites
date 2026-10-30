import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Check, ChevronDown, Globe, Square } from "lucide-react";
import { api } from "../../lib/api";
import { modelLabel, useModels } from "../../lib/models";
import type { Mode, ThinkingSetting } from "../../lib/types";
import { MenuItem, Popover, cn } from "../ui";

export interface ComposerSettings {
  mode: Mode;
  provider: string | null;
  model: string | null;
  thinking: ThinkingSetting | null;
  workspace_ids: string[];
}

type ReasoningLevel = "off" | "on" | "deep";

function reasoningLevel(t: ThinkingSetting | null): ReasoningLevel {
  if (t && t.enabled === false) return "off";
  if (t?.effort === "high") return "deep";
  return "on";
}

const REASONING: Record<ReasoningLevel, ThinkingSetting> = {
  off: { enabled: false, effort: null },
  on: { enabled: true, effort: null },
  deep: { enabled: true, effort: "high" },
};

function ModelPicker({
  settings,
  onChange,
}: {
  settings: ComposerSettings;
  onChange: (patch: Partial<ComposerSettings>) => void;
}) {
  const { data } = useModels();
  const current = {
    provider: settings.provider ?? data?.default ?? null,
    model: settings.model ?? (settings.provider ? null : data?.default_model ?? null),
  };
  const level = reasoningLevel(settings.thinking);

  return (
    <Popover
      side="top"
      align="end"
      className="w-80"
      trigger={({ open, toggle }) => (
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="flex max-w-40 items-center gap-1 rounded-md px-2 py-1 text-[13px] text-muted hover:bg-canvas hover:text-ink sm:max-w-52"
        >
          <span className="truncate">{modelLabel(data, settings.provider, settings.model)}</span>
          <ChevronDown size={13} className="shrink-0" />
        </button>
      )}
    >
      {(close) => (
        <div className="max-h-[60vh] overflow-y-auto">
          {data?.providers.map((p) => {
            const specs = p.specs.filter((s) => s.enabled);
            if (!specs.length && p.available) return null;
            return (
              <div key={p.provider} className="py-1">
                <div className="px-2.5 pt-1 pb-0.5 text-[12.5px] font-semibold text-ink">{p.label}</div>
                {!p.available && <p className="px-2.5 pb-1 text-[12px] text-faint">{p.reason}</p>}
                {p.available &&
                  specs.map((s) => {
                    const selected = current.provider === p.provider && current.model === s.id;
                    const caps = [s.supports_tools && "research", s.supports_thinking && "reasoning"].filter(Boolean).join(", ");
                    return (
                      <MenuItem
                        key={s.id}
                        onClick={() => {
                          onChange({ provider: p.provider, model: s.id });
                          close();
                        }}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-ink">{s.label}</span>
                          {caps && <span className="block text-[11.5px] text-faint">{caps}</span>}
                        </span>
                        {selected && <Check size={14} className="text-brand" />}
                      </MenuItem>
                    );
                  })}
              </div>
            );
          })}
          <div className="mt-1 border-t border-line px-2.5 pt-2.5 pb-1.5">
            <div className="mb-1.5 text-[12.5px] text-muted">Reasoning</div>
            <div className="grid grid-cols-3 gap-1 rounded-lg bg-canvas p-0.5" role="radiogroup" aria-label="Reasoning">
              {(["off", "on", "deep"] as const).map((l) => (
                <button
                  key={l}
                  type="button"
                  role="radio"
                  aria-checked={level === l}
                  onClick={() => onChange({ thinking: REASONING[l] })}
                  className={cn(
                    "rounded-md py-1 text-[12.5px] capitalize",
                    level === l ? "bg-surface font-medium text-ink shadow-sm" : "text-muted hover:text-ink",
                  )}
                >
                  {l}
                </button>
              ))}
            </div>
            <Link to="/settings/models" onClick={close} className="mt-2.5 block text-[12.5px] text-brand hover:underline">
              Manage models
            </Link>
          </div>
        </div>
      )}
    </Popover>
  );
}

function SitesScope({
  selected,
  onChange,
}: {
  selected: string[];
  onChange: (ids: string[]) => void;
}) {
  const { data: sites } = useQuery({ queryKey: ["workspaces"], queryFn: api.listWorkspaces });
  const names = (sites ?? []).filter((s) => selected.includes(s.id)).map((s) => s.name);
  const label = !selected.length ? "All sites" : names.length === 1 ? names[0] : `${names.length} sites`;
  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);

  return (
    <Popover
      side="top"
      className="w-72"
      trigger={({ open, toggle: t }) => (
        <button
          type="button"
          onClick={t}
          aria-expanded={open}
          className="flex max-w-48 items-center gap-1.5 rounded-md px-2 py-1 text-[13px] text-muted hover:bg-canvas hover:text-ink"
        >
          <Globe size={13} className="shrink-0" />
          <span className="truncate">{label}</span>
        </button>
      )}
    >
      <MenuItem onClick={() => onChange([])}>
        <span className="flex-1">All indexed sites</span>
        {!selected.length && <Check size={14} className="text-brand" />}
      </MenuItem>
      <div className="my-1 border-t border-line" />
      {(sites ?? []).map((s) => (
        <MenuItem key={s.id} onClick={() => toggle(s.id)} disabled={s.chunk_count === 0}>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-ink">{s.name}</span>
            <span className="block text-[11.5px] text-faint">
              {s.status === "ready" ? `${s.page_count} pages` : s.status}
            </span>
          </span>
          {selected.includes(s.id) && <Check size={14} className="text-brand" />}
        </MenuItem>
      ))}
      {!sites?.length && <p className="px-2.5 py-2 text-[13px] text-muted">No sites yet. Add one from the sidebar.</p>}
    </Popover>
  );
}

export function Composer({
  settings,
  onSettings,
  onSend,
  onStop,
  busy,
  autoFocus,
  placeholder = "Ask about your sites…",
  draftKey,
}: {
  settings: ComposerSettings;
  onSettings: (patch: Partial<ComposerSettings>) => void;
  onSend: (prompt: string) => void;
  onStop?: () => void;
  busy?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
  draftKey?: string;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setText("");
    if (autoFocus) ref.current?.focus();
  }, [draftKey, autoFocus]);

  // Grow with the text up to a sensible height.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  }, [text]);

  const submit = () => {
    const prompt = text.trim();
    if (!prompt || busy) return;
    onSend(prompt);
    setText("");
  };

  return (
    <div className="rounded-2xl border border-line-strong bg-surface shadow-[0_8px_24px_-16px_rgb(15_20_30/0.25)] focus-within:border-brand">
      <textarea
        ref={ref}
        rows={1}
        value={text}
        autoFocus={autoFocus}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder={placeholder}
        aria-label="Your question"
        className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-1.5 text-[15.5px] text-ink placeholder:text-faint focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-1 px-2 pb-2">
        <div className="flex rounded-lg bg-canvas p-0.5" role="radiogroup" aria-label="Answer style">
          {(
            [
              ["rag", "Quick answer", "Search once, then answer. Works with every model."],
              ["agent", "Research", "The model searches and reads pages as many times as it needs."],
            ] as const
          ).map(([value, label, hint]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={settings.mode === value}
              title={hint}
              onClick={() => onSettings({ mode: value })}
              className={cn(
                "rounded-md px-2.5 py-1 text-[13px] whitespace-nowrap",
                settings.mode === value ? "bg-surface font-medium text-ink shadow-sm" : "text-muted hover:text-ink",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <SitesScope selected={settings.workspace_ids} onChange={(ids) => onSettings({ workspace_ids: ids })} />
        <div className="ml-auto flex items-center gap-1">
          <ModelPicker settings={settings} onChange={onSettings} />
          {busy ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="Stop answering"
              className="grid h-8 w-8 place-items-center rounded-lg bg-ink text-canvas"
            >
              <Square size={12} fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={!text.trim()}
              aria-label="Send"
              className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-white disabled:bg-line-strong disabled:text-faint dark:text-canvas"
            >
              <ArrowUp size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
