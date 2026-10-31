/**
 * Typed API client.
 *
 * Replaces the `const API_BASE = "http://localhost:8000"` that was duplicated
 * across three components, and normalises errors so callers get a real message
 * instead of a raw fetch rejection.
 */

import type {
  AnswerPayload,
  CompareResponse,
  DocumentsResponse,
  Engine,
  GraphResponse,
  HealthResponse,
  Job,
  McpServer,
  ModelsResponse,
  PageRecord,
  SearchHit,
  Session,
  SessionDetail,
  ToolInfo,
  Workspace,
} from "./types";

export const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "";

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch (err) {
    throw new ApiError(
      err instanceof Error ? `Cannot reach the API: ${err.message}` : "Network error",
      0,
    );
  }

  const raw = await res.text();
  let body: unknown = null;
  if (raw) {
    try {
      body = JSON.parse(raw);
    } catch {
      body = raw;
    }
  }

  if (!res.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    throw new ApiError(
      typeof detail === "string" ? detail : `Request failed (${res.status})`,
      res.status,
      detail,
    );
  }
  return body as T;
}

const json = (data: unknown): RequestInit => ({
  method: "POST",
  body: JSON.stringify(data),
});

export const api = {
  health: () => request<HealthResponse>("/health"),

  models: () => request<ModelsResponse>("/models"),

  updateModel: (provider: string, model: string, patch: { enabled?: boolean; is_default?: boolean }) =>
    request<ModelsResponse>(`/models/${provider}/${model}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  addModel: (provider: string, model_id: string, make_default = false) =>
    request<ModelsResponse>("/models", json({ provider, model_id, make_default })),

  resetModel: (provider: string, model: string) =>
    request<ModelsResponse>(`/models/${provider}/${model}`, { method: "DELETE" }),

  // ── sessions ─────────────────────────────────────────────────────────

  listSessions: (workspaceId?: string) => {
    const params = workspaceId ? `?workspace_id=${workspaceId}` : "";
    return request<{ sessions: Session[] }>(`/sessions${params}`).then((r) => r.sessions);
  },

  createSession: (input: Partial<Omit<Session, "id" | "created_at" | "updated_at">>) =>
    request<{ session: Session }>("/sessions", json(input)).then((r) => r.session),

  getSession: (id: string) => request<SessionDetail>(`/sessions/${id}`),

  updateSession: (id: string, patch: Partial<Session>) =>
    request<{ session: Session }>(`/sessions/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }).then((r) => r.session),

  deleteSession: (id: string) =>
    request<{ deleted: boolean }>(`/sessions/${id}`, { method: "DELETE" }),

  cancelSession: (id: string) =>
    request<{ cancelled: boolean }>(`/sessions/${id}/cancel`, { method: "POST" }),

  forkSession: (id: string, turnId?: string) =>
    request<{ session: Session }>(`/sessions/${id}/fork`, json({ turn_id: turnId ?? null })).then(
      (r) => r.session,
    ),

  searchSessions: (q: string) =>
    request<{ results: SearchHit[] }>(`/sessions/search?q=${encodeURIComponent(q)}`).then(
      (r) => r.results,
    ),

  exportUrl: (id: string, format: "markdown" | "json") =>
    `${API_BASE}/sessions/${id}/export?format=${format}`,

  feedback: (messageId: string, value: -1 | 0 | 1) =>
    request<{ feedback: number }>(`/messages/${messageId}/feedback`, json({ value })),

  // ── tools & MCP ──────────────────────────────────────────────────────

  tools: () => request<{ tools: ToolInfo[] }>("/tools").then((r) => r.tools),

  setTool: (name: string, enabled: boolean) =>
    request<{ tools: ToolInfo[] }>(`/tools/${name}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }).then((r) => r.tools),

  mcpServers: () => request<{ servers: McpServer[] }>("/mcp/servers").then((r) => r.servers),

  addMcpServer: (input: Partial<McpServer>) =>
    request<{ servers: McpServer[] }>("/mcp/servers", json(input)).then((r) => r.servers),

  updateMcpServer: (id: string, patch: Partial<McpServer>) =>
    request<{ servers: McpServer[] }>(`/mcp/servers/${id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }).then((r) => r.servers),

  deleteMcpServer: (id: string) =>
    request<{ servers: McpServer[] }>(`/mcp/servers/${id}`, { method: "DELETE" }).then(
      (r) => r.servers,
    ),

  testMcpServer: (id: string) =>
    request<{ ok: boolean; tools: { name: string; description: string }[] }>(
      `/mcp/servers/${id}/test`,
      { method: "POST" },
    ),

  listWorkspaces: () =>
    request<{ workspaces: Workspace[] }>("/workspaces").then((r) => r.workspaces),

  getWorkspace: (id: string) =>
    request<{ workspace: Workspace }>(`/workspaces/${id}`).then((r) => r.workspace),

  createWorkspace: (input: {
    seed_url: string;
    name?: string;
    mode: "page" | "site";
    max_pages?: number;
    max_depth?: number;
  }) =>
    request<{ workspace: Workspace; job: Job | null }>(
      "/workspaces",
      json({ ...input, start: true }),
    ),

  deleteWorkspace: (id: string) =>
    request<{ deleted: boolean }>(`/workspaces/${id}`, { method: "DELETE" }),

  reindex: (id: string, recrawl = true) =>
    request<{ job: Job }>(`/workspaces/${id}/reindex?recrawl=${recrawl}`, {
      method: "POST",
    }).then((r) => r.job),

  documents: (id: string, page = 1, pageSize = 25, q?: string) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (q) params.set("q", q);
    return request<DocumentsResponse>(`/workspaces/${id}/documents?${params}`);
  },

  pages: (id: string) =>
    request<{ seed_url: string; pages: PageRecord[]; page_count: number }>(
      `/workspaces/${id}/pages`,
    ),

  graph: (id: string) => request<GraphResponse>(`/workspaces/${id}/graph`),

  query: (
    id: string,
    body: { prompt: string; engine: Engine; top_k: number; provider?: string; model?: string },
  ) => request<AnswerPayload>(`/workspaces/${id}/query`, json(body)),

  compare: (id: string, prompt: string, top_k: number) =>
    request<CompareResponse>(
      `/workspaces/${id}/retrieval/compare`,
      json({ prompt, top_k }),
    ),

  jobs: (workspaceId?: string) => {
    const params = workspaceId ? `?workspace_id=${workspaceId}` : "";
    return request<{ jobs: Job[] }>(`/jobs${params}`).then((r) => r.jobs);
  },

  job: (id: string) => request<Job>(`/jobs/${id}`),

  cancelJob: (id: string) =>
    request<{ cancelled: boolean }>(`/jobs/${id}/cancel`, { method: "POST" }),
};
