import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { api } from "../../lib/api";
import { ErrorNote } from "../ui";
import { Composer, type ComposerSettings } from "./Composer";

const DRAFT_KEY = "askthesite.newchat";

function storedDraft(): Pick<ComposerSettings, "mode" | "thinking"> {
  try {
    const raw = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}");
    return { mode: raw.mode === "agent" ? "agent" : "rag", thinking: raw.thinking ?? null };
  } catch {
    return { mode: "rag", thinking: null };
  }
}

export default function NewChatPage({ onAddSite }: { onAddSite: () => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const sites = useQuery({ queryKey: ["workspaces"], queryFn: api.listWorkspaces });
  const recent = useQuery({ queryKey: ["sessions"], queryFn: () => api.listSessions() });

  const [settings, setSettings] = useState<ComposerSettings>(() => ({
    ...storedDraft(),
    provider: null,
    model: null,
    workspace_ids: [],
  }));
  const [error, setError] = useState<unknown>(null);

  // Arriving from "Ask this site" preselects it.
  const preselect = params.get("site");
  useEffect(() => {
    setSettings((s) => ({ ...s, workspace_ids: preselect ? [preselect] : [] }));
  }, [preselect]);

  const update = (patch: Partial<ComposerSettings>) =>
    setSettings((s) => {
      const next = { ...s, ...patch };
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ mode: next.mode, thinking: next.thinking }));
      } catch {
        /* storage unavailable */
      }
      return next;
    });

  const start = async (prompt: string) => {
    setError(null);
    try {
      const session = await api.createSession({
        mode: settings.mode,
        workspace_ids: settings.workspace_ids,
        thinking: settings.thinking,
        ...(settings.provider ? { provider: settings.provider, model: settings.model } : {}),
      });
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
      navigate(`/c/${session.id}`, { state: { pending: prompt } });
    } catch (err) {
      setError(err);
    }
  };

  const ready = (sites.data ?? []).filter((s) => s.chunk_count > 0);
  const scoped = ready.filter((s) => settings.workspace_ids.includes(s.id));

  return (
    <div className="flex min-h-svh flex-col px-5 pt-[14vh] pb-10">
      <div className="mx-auto w-full max-w-[44rem]">
        <h1 className="font-serif text-[2.35rem] leading-tight font-semibold tracking-[-0.01em] text-ink">
          {scoped.length === 1 ? `Ask ${scoped[0].name}` : "What do you want to find out?"}
        </h1>
        <p className="mt-2 mb-7 text-[15px] text-muted">
          {sites.isLoading
            ? " "
            : ready.length
              ? `Answers come from ${ready.length === 1 ? "your indexed site" : `${ready.length} indexed sites`}, with every claim linked to the passage behind it.`
              : "Add a website first. AskTheSite reads it, then answers from it with citations."}
        </p>

        {!sites.isLoading && ready.length === 0 ? (
          <button
            type="button"
            onClick={onAddSite}
            className="flex w-full items-center gap-3 rounded-2xl border border-dashed border-line-strong bg-surface px-5 py-5 text-left hover:border-brand"
          >
            <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-soft text-brand">
              <Plus size={18} />
            </span>
            <span>
              <span className="block font-semibold text-ink">Add a site</span>
              <span className="block text-sm text-muted">Paste a docs URL; crawling takes a minute or two.</span>
            </span>
          </button>
        ) : (
          <Composer settings={settings} onSettings={update} onSend={start} autoFocus />
        )}
        {error != null && (
          <div className="mt-3">
            <ErrorNote error={error} />
          </div>
        )}

        {(recent.data?.length ?? 0) > 0 && (
          <section className="mt-14">
            <h2 className="mb-2 text-[13.5px] font-semibold text-muted">Pick up where you left off</h2>
            <ul className="divide-y divide-line border-y border-line">
              {recent.data!.slice(0, 5).map((s) => (
                <li key={s.id}>
                  <Link
                    to={`/c/${s.id}`}
                    className="flex items-baseline gap-3 py-2.5 text-[14.5px] text-body hover:text-ink"
                  >
                    <span className="min-w-0 flex-1 truncate">{s.title}</span>
                    <span className="shrink-0 text-[12.5px] text-faint">
                      {new Date(s.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
