import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, GitFork, MoreHorizontal, Pin, PinOff, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import { fromStored, useChatStream, type TurnModel } from "../../lib/chat";
import type { Session, SessionDetail } from "../../lib/types";
import { ErrorNote, IconButton, MenuItem, Popover, Spinner } from "../ui";
import { Composer, type ComposerSettings } from "./Composer";
import { Inspector, type InspectorTab } from "./Inspector";
import { TurnView } from "./TurnView";

function settingsOf(s: Session): ComposerSettings {
  return {
    mode: s.mode,
    provider: s.provider,
    model: s.model,
    thinking: s.thinking,
    workspace_ids: s.workspace_ids,
  };
}

function TitleEditor({ session }: { session: Session }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(session.title);
  useEffect(() => setValue(session.title), [session.title]);

  const save = async () => {
    setEditing(false);
    const title = value.trim();
    if (!title || title === session.title) return setValue(session.title);
    const updated = await api.updateSession(session.id, { title });
    queryClient.setQueryData<SessionDetail>(["session", session.id], (d) => (d ? { ...d, session: updated } : d));
    queryClient.invalidateQueries({ queryKey: ["sessions"] });
  };

  return editing ? (
    <input
      autoFocus
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") {
          setValue(session.title);
          setEditing(false);
        }
      }}
      aria-label="Chat title"
      className="w-full min-w-0 rounded-md border border-brand bg-surface px-2 py-0.5 text-[15px] font-semibold text-ink focus:outline-none"
    />
  ) : (
    <button
      type="button"
      onClick={() => setEditing(true)}
      title="Rename"
      className="block max-w-full truncate rounded-md px-2 py-0.5 text-left text-[15px] font-semibold text-ink hover:bg-canvas"
    >
      {session.title}
    </button>
  );
}

function SessionMenu({ session }: { session: Session }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["sessions"] });

  return (
    <Popover
      align="end"
      trigger={({ open, toggle }) => (
        <IconButton aria-label="Chat options" aria-expanded={open} onClick={toggle} active={open}>
          <MoreHorizontal size={17} />
        </IconButton>
      )}
    >
      {(close) => (
        <>
          <MenuItem
            onClick={async () => {
              const updated = await api.updateSession(session.id, { pinned: !session.pinned });
              queryClient.setQueryData<SessionDetail>(["session", session.id], (d) => (d ? { ...d, session: updated } : d));
              refresh();
              close();
            }}
          >
            {session.pinned ? <PinOff size={15} /> : <Pin size={15} />}
            {session.pinned ? "Unpin" : "Pin to top"}
          </MenuItem>
          <MenuItem
            onClick={async () => {
              const copy = await api.forkSession(session.id);
              refresh();
              close();
              navigate(`/c/${copy.id}`);
            }}
          >
            <GitFork size={15} />
            Duplicate chat
          </MenuItem>
          <a href={api.exportUrl(session.id, "markdown")} onClick={close} className="block">
            <MenuItem tabIndex={-1}>
              <Download size={15} />
              Download as Markdown
            </MenuItem>
          </a>
          <a href={api.exportUrl(session.id, "json")} onClick={close} className="block">
            <MenuItem tabIndex={-1}>
              <Download size={15} />
              Download as JSON
            </MenuItem>
          </a>
          <div className="my-1 border-t border-line" />
          <MenuItem
            danger
            onClick={async () => {
              if (!confirm(`Delete “${session.title}”? This can’t be undone.`)) return;
              await api.deleteSession(session.id);
              refresh();
              close();
              navigate("/");
            }}
          >
            <Trash2 size={15} />
            Delete chat
          </MenuItem>
        </>
      )}
    </Popover>
  );
}

export default function ChatPage() {
  const { sessionId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const detail = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => api.getSession(sessionId!),
    enabled: !!sessionId,
  });
  const { live, replacing, send, stop, dismissError, busy } = useChatStream(sessionId);

  const [inspector, setInspector] = useState<{ key: string; tab: InspectorTab; marker: number | null } | null>(null);
  useEffect(() => setInspector(null), [sessionId]);

  // A question typed on the new-chat page arrives as navigation state.
  const pendingSent = useRef<string | null>(null);
  useEffect(() => {
    const pending = (location.state as { pending?: string } | null)?.pending;
    if (pending && sessionId && pendingSent.current !== sessionId && detail.data) {
      pendingSent.current = sessionId;
      navigate(location.pathname, { replace: true, state: null });
      send({ prompt: pending });
    }
  }, [location, sessionId, detail.data, navigate, send]);

  const settings = useMutation({
    mutationFn: (patch: Partial<ComposerSettings>) => api.updateSession(sessionId!, patch as Partial<Session>),
    onSuccess: (updated) => {
      queryClient.setQueryData<SessionDetail>(["session", sessionId], (d) => (d ? { ...d, session: updated } : d));
      queryClient.invalidateQueries({ queryKey: ["sessions"] });
    },
  });

  const turns: TurnModel[] = useMemo(() => {
    // While a turn streams, the server already holds its question; show the
    // live copy only, or it appears twice.
    const stored = (detail.data?.turns ?? []).filter((t) => !live?.turnId || t.turn_id !== live.turnId);
    const cut = replacing ? stored.findIndex((t) => t.turn_id === replacing) : -1;
    const shown = (cut >= 0 ? stored.slice(0, cut) : stored).map(fromStored);
    return live ? [...shown, live] : shown;
  }, [detail.data, live, replacing]);

  // Follow the answer as it streams, unless the reader scrolled up.
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const onScroll = () => {
    const el = scroller.current;
    if (el) pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [turns]);
  useEffect(() => {
    pinned.current = true;
  }, [sessionId]);

  const ask = useCallback((prompt: string) => {
    pinned.current = true;
    send({ prompt });
  }, [send]);

  if (detail.isLoading) {
    return (
      <div className="grid h-svh place-items-center text-muted">
        <Spinner />
      </div>
    );
  }
  if (detail.error || !detail.data) {
    return (
      <div className="mx-auto max-w-xl p-10">
        <ErrorNote error={detail.error ?? "This chat doesn’t exist any more."} />
      </div>
    );
  }

  const session = detail.data.session;
  const selected = inspector ? turns.find((t) => t.key === inspector.key) : undefined;

  return (
    <div className="flex h-svh min-w-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-4 pl-14 md:pl-4">
          <div className="min-w-0 flex-1">
            <TitleEditor session={session} />
          </div>
          <SessionMenu session={session} />
        </header>

        <div ref={scroller} onScroll={onScroll} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[44rem] space-y-12 px-5 pt-8 pb-10">
            {turns.length === 0 && (
              <p className="pt-16 text-muted">Ask a question below. Answers cite the passages they come from.</p>
            )}
            {turns.map((turn, i) => (
              <TurnView
                key={turn.key}
                turn={turn}
                isLast={i === turns.length - 1}
                busy={busy}
                activeMarker={inspector?.key === turn.key ? inspector.marker : null}
                onPickCitation={(key, marker) => setInspector({ key, tab: "sources", marker })}
                onOpenInspector={(key) => setInspector({ key, tab: "sources", marker: null })}
                onRetry={(turnId) => send({ prompt: turn.question, replaceTurnId: turnId })}
                onEdit={(turnId, prompt) => send({ prompt, replaceTurnId: turnId })}
                onFollowUp={ask}
                onDismissError={turn === live ? dismissError : undefined}
              />
            ))}
          </div>
        </div>

        <div className="shrink-0 px-5 pb-5">
          <div className="mx-auto max-w-[44rem]">
            <Composer
              settings={settingsOf(session)}
              onSettings={(patch) => settings.mutate(patch)}
              onSend={ask}
              onStop={stop}
              busy={busy}
              autoFocus
              draftKey={sessionId}
              placeholder={turns.length ? "Ask a follow-up…" : "Ask about your sites…"}
            />
            {settings.error && <p className="mt-2 text-[13px] text-bad">{String((settings.error as Error).message)}</p>}
          </div>
        </div>
      </div>

      {inspector && selected && (
        <Inspector
          turn={selected}
          tab={inspector.tab}
          onTab={(tab) => setInspector({ ...inspector, tab })}
          activeMarker={inspector.marker}
          sessionUsage={session.usage}
          onClose={() => setInspector(null)}
        />
      )}
    </div>
  );
}
