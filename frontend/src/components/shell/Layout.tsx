import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Menu, Moon, PenSquare, Plus, Search, Settings, Sun, X } from "lucide-react";
import { api } from "../../lib/api";
import type { ShellContext } from "../../lib/shell";
import { applyTheme, storedTheme, type Theme } from "../../lib/theme";
import type { Session, Workspace } from "../../lib/types";
import NewWorkspaceDialog from "../NewWorkspaceDialog";
import { IconButton, Kbd, cn } from "../ui";
import CommandPalette from "./CommandPalette";

const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

function Wordmark() {
  return (
    <span className="flex items-center gap-2">
      <span aria-hidden className="relative grid h-6 w-6 place-items-center rounded-md bg-ink">
        <span className="h-1.5 w-3.5 rounded-[2px] bg-mark" />
      </span>
      <span className="font-serif text-[17px] font-semibold tracking-[-0.01em] text-ink">AskTheSite</span>
    </span>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(storedTheme);
  useEffect(() => applyTheme(theme), [theme]);
  const dark = document.documentElement.classList.contains("dark");
  return (
    <IconButton aria-label={dark ? "Use light theme" : "Use dark theme"} onClick={() => setTheme(dark ? "light" : "dark")}>
      {dark ? <Sun size={16} /> : <Moon size={16} />}
    </IconButton>
  );
}

const STATUS_DOT: Record<string, string> = {
  ready: "bg-good",
  failed: "bg-bad",
  empty: "bg-line-strong",
};

function SiteLink({ site }: { site: Workspace }) {
  return (
    <NavLink
      to={`/sites/${site.id}/lab`}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[14px]",
          isActive ? "bg-surface text-ink shadow-sm" : "text-body hover:bg-surface/60 hover:text-ink",
        )
      }
    >
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", STATUS_DOT[site.status] ?? "animate-pulse bg-warn")} />
      <span className="min-w-0 flex-1 truncate">{site.name}</span>
      <span className="shrink-0 text-[12px] text-faint">{site.status === "ready" ? site.page_count : site.status}</span>
    </NavLink>
  );
}

function ChatLink({ session }: { session: Session }) {
  return (
    <NavLink
      to={`/c/${session.id}`}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2 rounded-md px-2.5 py-1.5 text-[14px]",
          isActive ? "bg-surface text-ink shadow-sm" : "text-body hover:bg-surface/60 hover:text-ink",
        )
      }
    >
      <span className="min-w-0 flex-1 truncate">{session.title}</span>
      {session.running && <span className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-brand" aria-label="Answering" />}
    </NavLink>
  );
}

function Sidebar({ onAddSite, onSearch }: { onAddSite: () => void; onSearch: () => void }) {
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15_000 });
  const sites = useQuery({ queryKey: ["workspaces"], queryFn: api.listWorkspaces, refetchInterval: 8_000 });
  const sessions = useQuery({ queryKey: ["sessions"], queryFn: () => api.listSessions(), refetchInterval: 15_000 });

  const pinned = (sessions.data ?? []).filter((s) => s.pinned);
  const recent = (sessions.data ?? []).filter((s) => !s.pinned).slice(0, 40);

  return (
    <nav aria-label="Main" className="flex h-full w-[17rem] flex-col bg-sidebar">
      <div className="flex h-14 items-center justify-between px-4">
        <NavLink to="/" aria-label="AskTheSite home">
          <Wordmark />
        </NavLink>
        <ThemeToggle />
      </div>

      <div className="space-y-1 px-3">
        <NavLink
          to="/"
          end
          className="flex items-center gap-2.5 rounded-md border border-line bg-surface px-2.5 py-1.5 text-[14px] font-medium text-ink hover:border-line-strong"
        >
          <PenSquare size={15} />
          New chat
        </NavLink>
        <button
          type="button"
          onClick={onSearch}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[14px] text-muted hover:bg-surface/60 hover:text-ink"
        >
          <Search size={15} />
          <span className="flex-1 text-left">Search</span>
          <Kbd>{isMac ? "⌘K" : "Ctrl K"}</Kbd>
        </button>
      </div>

      <div className="mt-5 flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        <section>
          <div className="flex items-center justify-between px-2.5 pb-1">
            <NavLink to="/sites" className="text-[13px] font-semibold text-muted hover:text-ink">
              Sites
            </NavLink>
            <button type="button" onClick={onAddSite} aria-label="Add a site" className="rounded p-0.5 text-muted hover:text-ink">
              <Plus size={15} />
            </button>
          </div>
          {(sites.data ?? []).map((s) => <SiteLink key={s.id} site={s} />)}
          {sites.data?.length === 0 && (
            <button type="button" onClick={onAddSite} className="px-2.5 py-1 text-left text-[13.5px] text-brand hover:underline">
              Add your first site
            </button>
          )}
        </section>

        {pinned.length > 0 && (
          <section>
            <h2 className="px-2.5 pb-1 text-[13px] font-semibold text-muted">Pinned</h2>
            {pinned.map((s) => <ChatLink key={s.id} session={s} />)}
          </section>
        )}
        <section>
          <h2 className="px-2.5 pb-1 text-[13px] font-semibold text-muted">Chats</h2>
          {recent.map((s) => <ChatLink key={s.id} session={s} />)}
          {sessions.data?.length === 0 && <p className="px-2.5 text-[13.5px] text-faint">Your chats will appear here.</p>}
        </section>
      </div>

      <div className="border-t border-line px-3 py-2.5">
        <NavLink
          to="/settings/models"
          className={({ isActive }) =>
            cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[14px]",
              isActive ? "bg-surface text-ink" : "text-body hover:bg-surface/60 hover:text-ink",
            )
          }
        >
          <Settings size={15} />
          Settings
        </NavLink>
        <p className="mt-1.5 flex items-center gap-2 px-2.5 text-[12.5px] text-faint">
          <span className={cn("h-1.5 w-1.5 rounded-full", health.isSuccess ? "bg-good" : "bg-bad")} />
          {health.isSuccess
            ? health.data.llm_ready
              ? "Connected"
              : "Connected, no model ready"
            : "Can’t reach the API on :8000"}
        </p>
      </div>
    </nav>
  );
}

export default function Layout() {
  const location = useLocation();
  const [drawer, setDrawer] = useState(false);
  const [addSite, setAddSite] = useState(false);
  const [palette, setPalette] = useState(false);

  useEffect(() => setDrawer(false), [location.pathname]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette((p) => !p);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const sidebar = <Sidebar onAddSite={() => setAddSite(true)} onSearch={() => setPalette(true)} />;

  return (
    <div className="flex min-h-svh">
      <div className="sticky top-0 hidden h-svh shrink-0 border-r border-line md:block">{sidebar}</div>

      <button
        type="button"
        onClick={() => setDrawer(true)}
        aria-label="Open menu"
        className={cn("fixed top-3 left-3 z-30 rounded-md p-2 text-muted hover:bg-surface md:hidden", drawer && "hidden")}
      >
        <Menu size={18} />
      </button>
      {drawer && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-ink/30" onClick={() => setDrawer(false)} />
          <div className="animate-slide-in relative h-full w-fit border-r border-line shadow-xl">
            {sidebar}
            <IconButton aria-label="Close menu" onClick={() => setDrawer(false)} className="absolute top-3 right-[-2.75rem] bg-surface">
              <X size={16} />
            </IconButton>
          </div>
        </div>
      )}

      <main className="min-w-0 flex-1">
        <Outlet context={{ openAddSite: () => setAddSite(true) } satisfies ShellContext} />
      </main>

      <NewWorkspaceDialog open={addSite} onClose={() => setAddSite(false)} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} onAddSite={() => setAddSite(true)} />
    </div>
  );
}
