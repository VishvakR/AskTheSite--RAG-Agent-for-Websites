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

export interface ProviderInfo {
  provider: string;
  label: string;
  available: boolean;
  reason: string | null;
  models: string[];
  default_model: string;
  requires_key: boolean;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  workspaces: number;
  llm_ready: boolean;
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
