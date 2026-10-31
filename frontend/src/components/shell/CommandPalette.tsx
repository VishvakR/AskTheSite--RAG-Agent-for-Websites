import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileSearch, Globe, MessageSquare, PenSquare, Plus, Settings, SunMoon } from "lucide-react";
import { api } from "../../lib/api";
import { applyTheme } from "../../lib/theme";
import { cn } from "../ui";

interface Item {
  id: string;
  group: string;
  label: string;
  hint?: string;
  icon: ReactNode;
  run: () => void;
}

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** ⌘K: jump to a chat or site, search what was said, or run an action. */
export default function CommandPalette({
  open,
  onClose,
  onAddSite,
}: {
  open: boolean;
  onClose: () => void;
  onAddSite: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const debounced = useDebounced(query.trim(), 180);

  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.listSessions(), enabled: open });
  const sites = useQuery({ queryKey: ["workspaces"], queryFn: api.listWorkspaces, enabled: open });
  const hits = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => api.searchSessions(debounced),
    enabled: open && debounced.length >= 2,
  });

  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
      setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  const items = useMemo<Item[]>(() => {
    const q = query.trim().toLowerCase();
    const matches = (s: string) => !q || s.toLowerCase().includes(q);
    const go = (path: string) => () => {
      navigate(path);
      onClose();
    };
    const out: Item[] = [];
    const actions: Item[] = [
      { id: "new", group: "Actions", label: "New chat", icon: <PenSquare size={15} />, run: go("/") },
      { id: "add", group: "Actions", label: "Add a site", icon: <Plus size={15} />, run: () => { onClose(); onAddSite(); } },
      { id: "settings", group: "Actions", label: "Model settings", icon: <Settings size={15} />, run: go("/settings/models") },
      { id: "mcp", group: "Actions", label: "Connect an MCP server", icon: <Settings size={15} />, run: go("/settings/connections") },
      {
        id: "theme",
        group: "Actions",
        label: "Switch light or dark theme",
        icon: <SunMoon size={15} />,
        run: () => {
          applyTheme(document.documentElement.classList.contains("dark") ? "light" : "dark");
          onClose();
        },
      },
    ];
    out.push(...actions.filter((a) => matches(a.label)));
    for (const s of sites.data ?? []) {
      if (matches(s.name) || matches(s.seed_url)) {
        out.push({ id: `ask-${s.id}`, group: "Sites", label: `Ask ${s.name}`, hint: s.seed_url, icon: <Globe size={15} />, run: go(`/?site=${s.id}`) });
        out.push({ id: `lab-${s.id}`, group: "Sites", label: `Inspect ${s.name}`, hint: "retrieval lab, pages, graph", icon: <FileSearch size={15} />, run: go(`/sites/${s.id}/lab`) });
      }
    }
    for (const s of (sessions.data ?? []).filter((s) => matches(s.title)).slice(0, 8)) {
      out.push({ id: `chat-${s.id}`, group: "Chats", label: s.title, icon: <MessageSquare size={15} />, run: go(`/c/${s.id}`) });
    }
    const seen = new Set(out.map((i) => i.id));
    for (const h of hits.data ?? []) {
      const id = `hit-${h.message_id}`;
      if (seen.has(id)) continue;
      out.push({
        id,
        group: "In your chats",
        label: h.snippet.replace(/\[|\]/g, ""),
        hint: h.title,
        icon: <MessageSquare size={15} />,
        run: go(`/c/${h.session_id}`),
      });
    }
    return out;
  }, [query, sites.data, sessions.data, hits.data, navigate, onClose, onAddSite]);

  useEffect(() => setIndex(0), [query]);

  if (!open) return null;

  let lastGroup = "";
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-ink/25 px-4 pt-[12vh]" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-label="Command palette"
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-raised shadow-[0_24px_64px_-24px_rgb(15_20_30/0.45)]"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <input
          ref={input}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setIndex((i) => Math.min(i + 1, items.length - 1));
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setIndex((i) => Math.max(i - 1, 0));
            }
            if (e.key === "Enter") items[index]?.run();
          }}
          placeholder="Search chats and sites, or type a command…"
          aria-label="Search"
          className="w-full border-b border-line bg-transparent px-5 py-4 text-[16px] text-ink placeholder:text-faint focus:outline-none"
        />
        <ul className="max-h-[52vh] overflow-y-auto p-2" role="listbox">
          {items.map((item, i) => {
            const header = item.group !== lastGroup ? item.group : null;
            lastGroup = item.group;
            return (
              <li key={item.id}>
                {header && <div className="px-3 pt-2.5 pb-1 text-[12.5px] font-semibold text-muted">{header}</div>}
                <button
                  type="button"
                  role="option"
                  aria-selected={i === index}
                  onMouseEnter={() => setIndex(i)}
                  onClick={item.run}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[14.5px]",
                    i === index ? "bg-canvas text-ink" : "text-body",
                  )}
                >
                  <span className="shrink-0 text-muted">{item.icon}</span>
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  {item.hint && <span className="max-w-[40%] shrink-0 truncate text-[12.5px] text-faint">{item.hint}</span>}
                </button>
              </li>
            );
          })}
          {items.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-muted">
              {hits.isFetching ? "Searching…" : `Nothing matches “${query}”.`}
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}
