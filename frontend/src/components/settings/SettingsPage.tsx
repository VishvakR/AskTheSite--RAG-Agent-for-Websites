import { useState } from "react";
import { NavLink, Navigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star, Trash2 } from "lucide-react";
import { api } from "../../lib/api";
import type { McpServer, ModelsResponse, ToolInfo } from "../../lib/types";
import { Button, ErrorNote, Spinner, Switch, cn } from "../ui";
import { describeTool } from "../../lib/tools";

const SECTIONS = [
  ["models", "Models"],
  ["tools", "Tools"],
  ["connections", "Connections"],
] as const;

// ── models ────────────────────────────────────────────────────────────────

function contextLabel(tokens: number) {
  return tokens >= 1_000_000 ? `${tokens / 1_000_000}M context` : `${Math.round(tokens / 1000)}k context`;
}

function Models() {
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: ["models"], queryFn: api.models });
  const set = (data: ModelsResponse) => queryClient.setQueryData(["models"], data);
  const update = useMutation({
    mutationFn: (v: { provider: string; model: string; patch: { enabled?: boolean; is_default?: boolean } }) =>
      api.updateModel(v.provider, v.model, v.patch),
    onSuccess: set,
  });
  const remove = useMutation({
    mutationFn: (v: { provider: string; model: string }) => api.resetModel(v.provider, v.model),
    onSuccess: set,
  });
  const [provider, setProvider] = useState("opensource");
  const [modelId, setModelId] = useState("");
  const add = useMutation({
    mutationFn: () => api.addModel(provider, modelId.trim()),
    onSuccess: (data) => {
      set(data);
      setModelId("");
    },
  });

  if (models.isLoading) return <Spinner />;
  if (models.error) return <ErrorNote error={models.error} />;

  return (
    <div className="space-y-10">
      <p className="max-w-prose text-[14.5px] text-muted">
        Choose which models appear in the picker and which one new chats start with. Research mode needs a model that can use
        tools; models without tool support answer in quick mode.
      </p>

      {models.data!.providers.map((p) => (
        <section key={p.provider}>
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
            <h2 className="text-[16px] font-semibold text-ink">{p.label}</h2>
            <span className={cn("text-[13px]", p.available ? "text-good" : "text-faint")}>
              {p.available ? "Ready" : p.reason}
            </span>
          </div>
          {p.specs.length === 0 ? (
            <p className="text-[13.5px] text-faint">No models found. {p.provider === "opensource" ? "Pull one with ollama pull, or add one below." : "Add one below."}</p>
          ) : (
            <ul className="divide-y divide-line border-y border-line">
              {p.specs.map((s) => {
                const caps = [s.supports_tools && "research", s.supports_thinking && "reasoning", s.supports_vision && "images"].filter(Boolean);
                return (
                  <li key={s.id} className="flex items-center gap-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[14.5px] text-ink">
                        {s.label}
                        {s.label !== s.id && <span className="ml-2 text-[12.5px] text-faint">{s.id}</span>}
                      </p>
                      <p className="text-[12.5px] text-muted">
                        {[contextLabel(s.context_window), ...caps].join(", ")}
                        {s.custom && ", added by you"}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={!p.available || s.is_default}
                      onClick={() => update.mutate({ provider: p.provider, model: s.id, patch: { is_default: true, enabled: true } })}
                      className={cn(
                        "flex items-center gap-1.5 rounded-md px-2 py-1 text-[13px]",
                        s.is_default ? "text-mark-ink" : "text-muted hover:bg-canvas hover:text-ink disabled:opacity-40",
                      )}
                    >
                      <Star size={14} className={s.is_default ? "fill-mark text-mark-ink" : ""} />
                      {s.is_default ? "Default" : "Make default"}
                    </button>
                    {s.custom && (
                      <button
                        type="button"
                        aria-label={`Remove ${s.id}`}
                        onClick={() => remove.mutate({ provider: p.provider, model: s.id })}
                        className="rounded-md p-1 text-faint hover:text-bad"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                    <Switch
                      label={`Show ${s.label} in the picker`}
                      checked={s.enabled}
                      onChange={(enabled) => update.mutate({ provider: p.provider, model: s.id, patch: { enabled } })}
                    />
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ))}

      <section>
        <h2 className="text-[16px] font-semibold text-ink">Add a model by id</h2>
        <p className="mt-1 mb-3 text-[13.5px] text-muted">For releases the list doesn’t know yet, or models served under a custom name.</p>
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (modelId.trim()) add.mutate();
          }}
        >
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            aria-label="Provider"
            className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm text-ink"
          >
            {models.data!.providers.map((p) => (
              <option key={p.provider} value={p.provider}>{p.label}</option>
            ))}
          </select>
          <input
            value={modelId}
            onChange={(e) => setModelId(e.target.value)}
            placeholder="e.g. qwen3:14b"
            aria-label="Model id"
            className="min-w-56 flex-1 rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-faint focus:border-brand focus:outline-none"
          />
          <Button type="submit" variant="primary" loading={add.isPending} disabled={!modelId.trim()}>
            Add model
          </Button>
        </form>
        {add.error && <p className="mt-2 text-[13px] text-bad">{(add.error as Error).message}</p>}
      </section>
    </div>
  );
}

// ── tools ─────────────────────────────────────────────────────────────────

const RISK: Record<ToolInfo["risk"], string> = {
  read: "Reads your indexed sites",
  network: "Fetches pages from the internet",
  write: "Changes data",
  external: "Runs on a connected server",
};

function Tools() {
  const queryClient = useQueryClient();
  const tools = useQuery({ queryKey: ["tools"], queryFn: api.tools });
  const toggle = useMutation({
    mutationFn: (v: { name: string; enabled: boolean }) => api.setTool(v.name, v.enabled),
    onSuccess: (data) => queryClient.setQueryData(["tools"], data),
  });
  if (tools.isLoading) return <Spinner />;
  if (tools.error) return <ErrorNote error={tools.error} />;
  return (
    <div className="space-y-6">
      <p className="max-w-prose text-[14.5px] text-muted">
        In research mode the model decides which of these to use. Turning one off hides it from every chat.
      </p>
      <ul className="divide-y divide-line border-y border-line">
        {tools.data!.map((t) => (
          <li key={t.name} className="flex items-start gap-4 py-3">
            <div className="min-w-0 flex-1">
              <p className="text-[14.5px] text-ink">{describeTool({ name: t.name, arguments: {} }).text.replace(/ “”/, "")}</p>
              <p className="mt-0.5 text-[13.5px] text-muted">{t.description}</p>
              <p className="mt-1 text-[12.5px] text-faint">
                {RISK[t.risk]}
                {t.source !== "builtin" && `, from ${t.source.replace(/^mcp:/, "")}`}
              </p>
            </div>
            <Switch label={`Allow ${t.name}`} checked={t.enabled} onChange={(enabled) => toggle.mutate({ name: t.name, enabled })} />
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── connections (MCP) ─────────────────────────────────────────────────────

function parsePairs(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const i = line.indexOf("=");
    if (i > 0) out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
  }
  return out;
}

function AddServer({ onAdded }: { onAdded: (servers: McpServer[]) => void }) {
  const [transport, setTransport] = useState<"stdio" | "http">("stdio");
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [url, setUrl] = useState("");
  const [pairs, setPairs] = useState("");
  const add = useMutation({
    mutationFn: () => {
      const [cmd, ...args] = command.trim().split(/\s+/);
      return api.addMcpServer(
        transport === "stdio"
          ? { name: name.trim(), transport, command: cmd, args, env: parsePairs(pairs) }
          : { name: name.trim(), transport, url: url.trim(), headers: parsePairs(pairs) },
      );
    },
    onSuccess: (servers) => {
      onAdded(servers);
      setName("");
      setCommand("");
      setUrl("");
      setPairs("");
    },
  });
  const field = "w-full rounded-md border border-line bg-surface px-2.5 py-1.5 text-sm text-ink placeholder:text-faint focus:border-brand focus:outline-none";
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        add.mutate();
      }}
      className="space-y-3 rounded-xl border border-line bg-surface p-4"
    >
      <h3 className="font-semibold text-ink">Connect a server</h3>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name, e.g. github" aria-label="Name" className={field} required />
        <div className="flex rounded-lg bg-canvas p-0.5" role="radiogroup" aria-label="How to connect">
          {(["stdio", "http"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="radio"
              aria-checked={transport === t}
              onClick={() => setTransport(t)}
              className={cn("rounded-md px-3 py-1 text-[13px]", transport === t ? "bg-surface font-medium text-ink shadow-sm" : "text-muted")}
            >
              {t === "stdio" ? "Local command" : "Remote URL"}
            </button>
          ))}
        </div>
      </div>
      {transport === "stdio" ? (
        <input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx -y @modelcontextprotocol/server-everything" aria-label="Command" className={cn(field, "font-mono text-[13px]")} required />
      ) : (
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/mcp" aria-label="URL" className={field} required />
      )}
      <textarea
        value={pairs}
        onChange={(e) => setPairs(e.target.value)}
        rows={2}
        placeholder={transport === "stdio" ? "Environment, one per line: API_KEY=…" : "Headers, one per line: Authorization=Bearer …"}
        aria-label={transport === "stdio" ? "Environment variables" : "Headers"}
        className={cn(field, "font-mono text-[13px]")}
      />
      <div className="flex items-center gap-3">
        <Button type="submit" variant="primary" loading={add.isPending}>Connect</Button>
        {add.error && <p className="text-[13px] text-bad">{(add.error as Error).message}</p>}
      </div>
    </form>
  );
}

function Connections() {
  const queryClient = useQueryClient();
  const servers = useQuery({ queryKey: ["mcp"], queryFn: api.mcpServers, refetchInterval: 10_000 });
  const set = (data: McpServer[]) => {
    queryClient.setQueryData(["mcp"], data);
    queryClient.invalidateQueries({ queryKey: ["tools"] });
  };
  const [tested, setTested] = useState<Record<string, string>>({});
  const update = useMutation({
    mutationFn: (v: { id: string; patch: Partial<McpServer> }) => api.updateMcpServer(v.id, v.patch),
    onSuccess: set,
  });
  const remove = useMutation({ mutationFn: (id: string) => api.deleteMcpServer(id), onSuccess: set });
  const test = async (id: string) => {
    setTested((t) => ({ ...t, [id]: "Connecting…" }));
    try {
      const res = await api.testMcpServer(id);
      setTested((t) => ({ ...t, [id]: `Works: ${res.tools.length} tool${res.tools.length === 1 ? "" : "s"}` }));
    } catch (err) {
      setTested((t) => ({ ...t, [id]: (err as Error).message }));
    }
  };

  return (
    <div className="space-y-6">
      <p className="max-w-prose text-[14.5px] text-muted">
        Tools from connected MCP servers become available to research mode alongside the site tools. AskTheSite is an MCP
        server too: point Claude Desktop or another client at <code className="rounded bg-canvas px-1 font-mono text-[13px]">uv run main.py mcp</code>,
        or at <code className="rounded bg-canvas px-1 font-mono text-[13px]">/mcp</code> on this API.
      </p>
      {servers.isLoading && <Spinner />}
      {servers.error && <ErrorNote error={servers.error} />}
      {(servers.data?.length ?? 0) > 0 && (
        <ul className="divide-y divide-line border-y border-line">
          {servers.data!.map((s) => (
            <li key={s.id} className="py-3">
              <div className="flex items-center gap-3">
                <span
                  className={cn("h-2 w-2 shrink-0 rounded-full", !s.enabled ? "bg-line-strong" : s.status.connected ? "bg-good" : "bg-bad")}
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <p className="text-[14.5px] text-ink">{s.name}</p>
                  <p className="truncate font-mono text-[12px] text-faint">
                    {s.transport === "stdio" ? [s.command, ...s.args].join(" ") : s.url}
                  </p>
                </div>
                <Button variant="ghost" onClick={() => test(s.id)}>Test</Button>
                <button type="button" aria-label={`Remove ${s.name}`} onClick={() => remove.mutate(s.id)} className="rounded-md p-1.5 text-faint hover:text-bad">
                  <Trash2 size={15} />
                </button>
                <Switch label={`Use ${s.name}`} checked={s.enabled} onChange={(enabled) => update.mutate({ id: s.id, patch: { enabled } })} />
              </div>
              <p className="mt-1 ml-5 text-[13px]">
                {!s.enabled ? (
                  <span className="text-faint">Off</span>
                ) : s.status.connected ? (
                  <span className="text-good">Connected, {s.status.tools.length} tools: <span className="text-muted">{s.status.tools.join(", ")}</span></span>
                ) : (
                  <span className="text-bad">{s.status.error ?? "Not connected"}</span>
                )}
                {tested[s.id] && <span className="ml-3 text-muted">{tested[s.id]}</span>}
              </p>
            </li>
          ))}
        </ul>
      )}
      <AddServer onAdded={set} />
    </div>
  );
}

export default function SettingsPage() {
  const { section } = useParams();
  if (!SECTIONS.some(([key]) => key === section)) return <Navigate to="/settings/models" replace />;
  return (
    <div className="mx-auto max-w-3xl px-5 pt-14 pb-16 md:pt-10">
      <h1 className="font-serif text-[1.9rem] font-semibold text-ink">Settings</h1>
      <nav className="mt-5 mb-8 flex gap-5 border-b border-line" aria-label="Settings sections">
        {SECTIONS.map(([key, label]) => (
          <NavLink
            key={key}
            to={`/settings/${key}`}
            className={({ isActive }) =>
              cn("-mb-px border-b-2 pb-2.5 text-[14.5px]", isActive ? "border-ink font-medium text-ink" : "border-transparent text-muted hover:text-ink")
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
      {section === "models" && <Models />}
      {section === "tools" && <Tools />}
      {section === "connections" && <Connections />}
    </div>
  );
}
