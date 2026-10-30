/** Mirrors the Pydantic models in server.py. */

export type Engine = "auto" | "bm25" | "rerank";
export type CrawlMode = "page" | "site";

export type WorkspaceStatus =
  | "empty"
  | "crawling"
  | "indexing"
  | "ready"
  | "failed";

export interface Workspace {
  id: string;
  name: string;
  seed_url: string;
  mode: CrawlMode;
  status: WorkspaceStatus;
  page_count: number;
  chunk_count: number;
  index_version: number;
  max_pages: number;
  max_depth: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  collection_name: string;
}

export type JobStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Job {
  id: string;
  workspace_id: string;
  kind: "crawl" | "ingest" | "full";
  status: JobStatus;
  phase: string;
  current: number;
  total: number;
  message: string;
  error: string | null;
  result: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  percent: number | null;
}

export interface Citation {
  rank: number;
  score: number;
  chunk_id: string | null;
  source_url: string;
  page_title: string;
  heading: string;
  page_id: string;
  chunk_index: number;
  snippet: string;
  marker: number;
}

export interface AnswerPayload {
  prompt: string;
  answer: string;
  citations: Citation[];
  engine: Engine;
  elapsed_ms: number;
  model: string;
}

export interface StrategyResult {
  engine: Engine;
  elapsed_ms: number;
  error: string | null;
  results: Citation[];
}

export interface PairwiseOverlap {
  shared_count: number;
  jaccard: number;
  shared: string[];
}

export interface CompareResponse {
  query: string;
  top_k: number;
  strategies: Record<Engine, StrategyResult>;
  overlap: {
    shared: string[];
    shared_count: number;
    union_count: number;
    agreement: number;
    pairwise: Record<string, PairwiseOverlap>;
    per_strategy: Record<Engine, string[]>;
  };
}

export interface ChunkRow {
  id: string | null;
  summary: string;
  length: number;
  source_url: string;
  page_title: string;
  heading: string;
  chunk_index: number;
  metadata: Record<string, unknown>;
}

export interface DocumentsResponse {
  documents: ChunkRow[];
  total_chunks: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface GraphNode {
  id: string;
  url: string;
  title: string;
  depth: number;
  char_count: number;
  chunk_count?: number;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: { source: string; target: string }[];
}

export interface ModelSpec {
  provider: string;
  id: string;
  key: string;
  label: string;
  context_window: number;
  supports_tools: boolean;
  supports_thinking: boolean;
  supports_vision: boolean;
  description: string;
  enabled: boolean;
  is_default: boolean;
  custom: boolean;
}

export interface ProviderInfo {
  provider: string;
  label: string;
  available: boolean;
  reason: string | null;
  /** Enabled model ids only. */
  models: string[];
  specs: ModelSpec[];
  default_model: string | null;
  requires_key: boolean;
}

export interface ModelsResponse {
  providers: ProviderInfo[];
  default: string;
  default_model: string | null;
}

// ── sessions ─────────────────────────────────────────────────────────────

export type Mode = "rag" | "agent";

export interface ThinkingSetting {
  enabled: boolean;
  effort?: "low" | "medium" | "high" | null;
}

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
}

export interface Session {
  id: string;
  title: string;
  workspace_ids: string[];
  provider: string | null;
  model: string | null;
  mode: Mode;
  engine: Engine;
  top_k: number;
  thinking: ThinkingSetting | null;
  system_prompt: string | null;
  pinned: boolean;
  usage: Usage | null;
  created_at: string;
  updated_at: string;
  running?: boolean;
}

export interface SourceCitation extends Citation {
  workspace_id?: string;
  workspace_name?: string;
}

export interface Grounding {
  score: number | null;
  label: "grounded" | "partly grounded" | "ungrounded" | "n/a";
  sentences: number;
  supported: number;
  uncited: string[];
  invalid_markers: number[];
  unused_sources: number[];
}

export interface TraceEntry {
  step?: number;
  kind: "model" | "tool" | "retrieve" | "cancelled";
  name?: string;
  elapsed_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  tool_calls?: number;
  is_error?: boolean;
  hits?: number;
  engine?: string;
  stop_reason?: string;
}

export interface ToolStep {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: string | null;
  preview?: string;
  is_error: boolean;
  elapsed_ms: number | null;
  done?: boolean;
}

export interface StoredAnswer {
  id: string;
  content: string;
  thinking: string | null;
  citations: SourceCitation[] | null;
  grounding: Grounding | null;
  followups: string[] | null;
  trace: TraceEntry[] | null;
  usage: Usage | null;
  provider: string | null;
  model: string | null;
  elapsed_ms: number | null;
  feedback: -1 | 0 | 1;
}

export interface Turn {
  turn_id: string;
  user: { id: string; content: string; created_at: string } | null;
  steps: ToolStep[];
  answer: StoredAnswer | null;
}

export interface SessionDetail {
  session: Session;
  turns: Turn[];
}

export interface SearchHit {
  message_id: string;
  session_id: string;
  title: string;
  role: string;
  created_at: string;
  snippet: string;
}

export interface ToolInfo {
  name: string;
  description: string;
  source: string;
  risk: "read" | "network" | "write" | "external";
  enabled: boolean;
  enabled_by_default: boolean;
  input_schema: Record<string, unknown>;
}

export interface McpServer {
  id: string;
  name: string;
  transport: "stdio" | "http";
  command: string | null;
  args: string[];
  env: Record<string, string>;
  url: string | null;
  headers: Record<string, string>;
  enabled: boolean;
  status: { connected: boolean; error: string | null; tools: string[] };
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  workspaces: number;
  llm_ready: boolean;
  mcp_connected?: number;
}

export interface PageRecord {
  url: string;
  title: string;
  depth: number;
  outlinks: string[];
  content_hash: string;
  char_count: number;
  crawled_at: string;
  page_id: string;
  file: string;
  error: string | null;
}
