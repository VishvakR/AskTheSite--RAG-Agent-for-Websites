# AskTheSite

Point it at a website, then ask questions about it — and see exactly how the
answer was found.

AskTheSite crawls a site, indexes it into a local vector store, and answers
questions with a retrieval-augmented pipeline. What makes it more than another
"chat with your docs" demo is that **the retrieval step is inspectable**: every
answer cites the exact chunks behind it, and you can run the same question
through all three retrieval strategies side by side and compare what each one
found.

Everything runs locally by default — no API key required.

---

## What's in it

| | |
|---|---|
| **Cited streaming chat** | Answers stream token by token with inline `[1]` citations. Click one to see the exact chunk, its heading, its relevance score and its source URL. |
| **Retrieval Lab** | Run one question through vector, BM25 and cross-encoder reranking at once. Comparable 0–1 scores, per-strategy latency, and which chunks the strategies agree on. |
| **Knowledge graph** | Every crawled page as a node, internal links as edges, coloured by link distance from the seed page and sized by how many chunks it contributed. |
| **Workspaces** | Index many sites side by side. Each gets its own collection, pages and history; deleting one cleans up after itself. |
| **Background jobs** | Crawling and embedding run in the background with live progress over SSE, so a 200-page crawl never blocks the API. |

---

## How it works

1. **Crawl** — [Crawl4AI](https://github.com/unclecode/crawl4ai) fetches pages
   (sitemap first, BFS fallback) and extracts clean markdown. Each page is
   written as its own file with YAML front-matter recording its URL, title and
   outlinks, plus a `manifest.json` holding the link graph.
2. **Ingest** — Markdown is split on its heading structure, then to size, so
   every chunk keeps the section it came from. Chunks are embedded with a
   sentence-transformer and stored in [ChromaDB](https://www.trychroma.com/),
   carrying `source_url`, `page_title`, `heading` and `chunk_index`.
3. **Retrieve** — One of three strategies returns ranked chunks *with scores*.
4. **Generate** — The numbered chunks are handed to an LLM that is instructed
   to cite them inline, so the markers in the answer map back to real sources.

### Retrieval strategies

| Strategy | How it works | Score |
|---|---|---|
| `auto` | Cosine similarity over embeddings. Finds meaning, misses exact terms. | `1 − distance/2` (always 0–1) |
| `bm25` | Classic keyword scoring. Nails exact terms, blind to synonyms. | Normalised by the batch maximum |
| `rerank` | Vector + BM25 candidate pools, rescored by a cross-encoder. Best quality, slowest. | Sigmoid of the cross-encoder logit |

`rerank` is usually the best and is the slowest — it loads a local
cross-encoder (cached after first use).

> BM25 needs a real corpus: on a handful of documents its IDF term is
> degenerate (a word appearing in 1 of 2 documents scores exactly 0), so it can
> legitimately return nothing on a tiny index.

---

## Quickstart

### Prerequisites

- Python 3.11+ and [uv](https://github.com/astral-sh/uv)
- Node 20+ (for the web UI)
- [Ollama](https://ollama.ai/) for the zero-key local path — or an Anthropic /
  OpenAI key

### 1. Install

```bash
git clone https://github.com/VishvakR/AskTheSite.git
cd AskTheSite

uv sync
uv run playwright install chromium     # the crawler needs a browser
cp .env.example .env
```

### 2. Pick a model

Local (no key needed) — pull any model and point `.env` at it:

```bash
ollama pull llama3.1:8b
```

```env
LLM_PROVIDER="opensource"
LLM_MODEL="llama3.1:8b"
```

Or use a hosted model:

```env
LLM_PROVIDER="anthropic"
LLM_MODEL="claude-opus-5"
ANTHROPIC_API_KEY="sk-ant-..."
```

`GET /models` reports which providers are actually usable right now, and why
one isn't — so a missing key or a stopped Ollama shows up immediately instead
of as an error at query time.

### 3. Run it

```bash
uv run uvicorn server:app --reload --port 8000    # API on :8000
cd frontend && npm install && npm run dev         # UI on :5173
```

Open <http://localhost:5173>, click **New**, and point it at a docs site.

---

## CLI

```bash
uv run main.py crawl https://docs.crawl4ai.com --mode site --max-pages 25
uv run main.py list
uv run main.py ask <workspace-id> "How do I install it?"
uv run main.py compare <workspace-id> "installation steps"
uv run main.py delete <workspace-id>
```

`compare` prints the three strategies side by side in the terminal — the same
data the Retrieval Lab renders.

---

## API

Interactive docs at <http://localhost:8000/docs>.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness plus whether any LLM is usable |
| `GET` | `/models` | Provider availability and why one is unavailable |
| `POST` | `/workspaces` | Create a workspace and start crawling; returns a job |
| `GET` | `/workspaces` | List workspaces |
| `GET`/`DELETE` | `/workspaces/{id}` | Fetch or delete one |
| `POST` | `/workspaces/{id}/reindex?recrawl=` | Rebuild the index |
| `GET` | `/workspaces/{id}/documents` | Paginated chunks with source metadata |
| `GET` | `/workspaces/{id}/pages` | Crawl manifest |
| `GET` | `/workspaces/{id}/graph` | Knowledge-graph nodes and edges |
| `POST` | `/workspaces/{id}/query` | Answer with citations |
| `POST` | `/workspaces/{id}/query/stream` | SSE: `sources` → `token` → `done` |
| `POST` | `/workspaces/{id}/retrieval/compare` | All three strategies at once |
| `GET` | `/jobs`, `/jobs/{id}` | Job status |
| `GET` | `/jobs/{id}/events` | SSE progress for a running job |

Streaming sends **sources first**, so a client can render citations while the
answer is still being written:

```bash
curl -N -X POST localhost:8000/workspaces/<id>/query/stream \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"How do I install it?","engine":"auto","top_k":5}'
```

---

## Project layout

```
AskTheSite/
├── app/
│   ├── catalog/      # SQLite catalog: workspaces, jobs, query history
│   ├── crawler/      # Crawl4AI wrapper, page front-matter, link manifest
│   ├── embeddings/   # Embedding model
│   ├── index/        # Chroma index + scored retrieval (retrieval.py)
│   ├── ingestion/    # Header-aware chunking with source metadata
│   ├── jobs/         # Background job runner with SSE progress
│   ├── llm/          # Provider registry: Ollama, Anthropic, OpenAI
│   ├── runtime/      # Cached embedding model, cross-encoder, BM25, stores
│   ├── services/     # Workspace orchestration
│   ├── storage/      # Vector store backends (Chroma, Qdrant, Mongo)
│   ├── config.py     # All settings, one place
│   └── main.py       # RAGAgent: retrieve → cite → generate
├── frontend/         # React 19 + Vite + Tailwind v4
├── tests/            # pytest, offline via a fake LLM provider
├── main.py           # CLI
└── server.py         # FastAPI app
```

---

## Docker

```bash
docker compose up --build
```

The compose file mounts named volumes for `storage/`, `workspaces/` and the
model cache, so the index survives restarts, and reaches an Ollama running on
the host via `host.docker.internal`.

---

## Tests

```bash
uv run pytest
```

The suite is fully offline: a fake LLM provider is registered through the same
factory the real ones use, and every test runs against a temporary storage
root, so it never touches your real index.

---

## Configuration

All settings live in `.env` (see `.env.example`). The most useful ones:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `opensource` | `opensource` (Ollama), `anthropic`, `openai` |
| `LLM_MODEL` | `qwen3.5:4b-mlx` | Model id for that provider |
| `PERSISTENT_STORAGE` | `./storage/cache` | Chroma index location |
| `WORKSPACE_ROOT` | `./workspaces` | Crawled markdown, per workspace |
| `CRAWL_MAX_PAGES` | `100` | Default page cap for a site crawl |
| `CRAWL_HEADLESS` | `true` | Must stay true outside a desktop session |
| `MAX_CONCURRENT_JOBS` | `2` | Parallel crawl/ingest jobs |

---

## License

MIT
