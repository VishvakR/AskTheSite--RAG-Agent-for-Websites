import { useEffect, useState } from "react";
import { NavLink, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Boxes,
  FileText,
  MessageSquare,
  Moon,
  Network,
  Plug,
  Plus,
  Sun,
  FlaskConical,
} from "lucide-react";
import { api } from "../lib/api";
import { applyTheme, storedTheme, type Theme } from "../lib/theme";
import type { Workspace } from "../lib/types";
import { Badge, Button, STATUS_TONE, cn } from "./ui";
import NewWorkspaceDialog from "./NewWorkspaceDialog";

const TABS = [
  { to: "chat", label: "Chat", icon: MessageSquare },
  { to: "lab", label: "Retrieval Lab", icon: FlaskConical },
  { to: "graph", label: "Graph", icon: Network },
  { to: "documents", label: "Documents", icon: FileText },
  { to: "api", label: "API", icon: Plug },
];

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(storedTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <button
      onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      aria-label="Toggle colour theme"
      className="rounded-lg p-2 text-muted transition-colors hover:bg-canvas hover:text-ink"
    >
      {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}

function WorkspacePicker({
  workspaces,
  active,
}: {
  workspaces: Workspace[];
  active?: string;
}) {
  const navigate = useNavigate();
  if (!workspaces.length) return null;

  return (
    <select
      value={active ?? ""}
      onChange={(e) => navigate(`/w/${e.target.value}/chat`)}
      aria-label="Active workspace"
      className="max-w-[15rem] truncate rounded-lg border border-line bg-surface px-2.5 py-1.5 text-sm text-body focus:border-brand focus:outline-none"
    >
      {workspaces.map((w) => (
        <option key={w.id} value={w.id}>
          {w.name}
        </option>
      ))}
    </select>
  );
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { workspaceId } = useParams();
  const [dialogOpen, setDialogOpen] = useState(false);

  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 15_000,
  });

  const workspaces = useQuery({
    queryKey: ["workspaces"],
    queryFn: api.listWorkspaces,
    refetchInterval: 8_000,
  });

  const online = health.isSuccess;
  const active = workspaces.data?.find((w) => w.id === workspaceId);

  return (
    <div className="min-h-svh bg-canvas">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-4 px-5">
          <NavLink to="/" className="flex shrink-0 items-center gap-2">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand text-white">
              <Boxes size={15} />
            </span>
            <span className="text-sm font-semibold tracking-tight text-ink">
              AskTheSite
            </span>
          </NavLink>

          <div className="h-5 w-px bg-line" />

          <WorkspacePicker
            workspaces={workspaces.data ?? []}
            active={workspaceId}
          />

          {active && (
            <Badge tone={STATUS_TONE[active.status] ?? "neutral"}>
              {active.status}
              {active.status === "ready" &&
                ` · ${active.page_count}p · ${active.chunk_count}c`}
            </Badge>
          )}

          <div className="ml-auto flex items-center gap-2">
            <span
              className="flex items-center gap-1.5 text-xs text-muted"
              title={
                online
                  ? "API reachable"
                  : "Cannot reach the API on port 8000"
              }
            >
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  online ? "bg-good" : "bg-bad",
                )}
              />
              {online ? "Connected" : "Offline"}
            </span>
            {online && !health.data?.llm_ready && (
              <Badge tone="warn">No LLM</Badge>
            )}
            <ThemeToggle />
            <Button variant="primary" onClick={() => setDialogOpen(true)}>
              <Plus size={15} />
              New
            </Button>
          </div>
        </div>

        {workspaceId && (
          <nav
            role="tablist"
            className="mx-auto flex max-w-[1400px] gap-1 px-5"
          >
            {TABS.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={`/w/${workspaceId}/${to}`}
                role="tab"
                className={({ isActive }) =>
                  cn(
                    "-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm transition-colors",
                    isActive
                      ? "border-brand font-medium text-ink"
                      : "border-transparent text-muted hover:text-body",
                  )
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </nav>
        )}
      </header>

      <main className="mx-auto max-w-[1400px] px-5 py-6">{children}</main>

      <NewWorkspaceDialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
      />
    </div>
  );
}
