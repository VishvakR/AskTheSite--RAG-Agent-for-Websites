# AskTheSite

Point it at a website, then ask questions about it — and see exactly how the
answer was found.

AskTheSite crawls a site, indexes it into a local vector store, and answers
questions about it. What makes it more than another "chat with your docs" demo
is that **every answer is checkable**: it cites the exact passages behind it,
a grounding meter flags the claims that cite nothing, and you can run the same
question through three retrieval strategies side by side to see what each one
found.

It works as a quick question-answerer or as a research agent that searches and
reads pages itself, in the browser, in the terminal, or from any MCP client
such as Claude Desktop.

Everything runs locally by default — no API key required.

---

## What's in it

| | |
|---|---|
| **Cited answers** | Answers stream with inline citation numbers. Hover one to read the passage; click it to open the source with its heading, score and URL. Numbers stay stable for a whole chat. |
| **Grounding meter** | After each answer, every claim is checked for a citation. You see "4 of 5 claims cite a source" and which sentence to double-check. |
| **Research mode** | The model drives: it searches (rephrasing when results are thin), reads full pages, lists pages and compares strategies, up to a step limit. Each step is shown in plain words. |
| **Visible reasoning** | Claude's extended thinking, Ollama's native thinking, and the `<think>` text local reasoning models write inline all stream into a collapsible "Reasoning" section instead of the answer. |
| **Chats with memory** | Sessions remember the conversation, can search one site, several, or all of them, and support edit, retry, duplicate, pin, Markdown/JSON export and full-text search. Long chats are summarised to fit small context windows. |
| **Any model** | Ollama, Anthropic, OpenAI, and any OpenAI-compatible server (LM Studio, vLLM, OpenRouter, Groq). Switch per chat; hide models or add new ones by id in Settings. |
| **MCP both ways** | Serve your indexed sites to Claude Desktop, Claude Code or Cursor, and give the agent tools from other MCP servers. |
| **Terminal app** | A full-screen Textual UI with the same chats, reasoning, tool trace and sources. |
| **Retrieval Lab** | Run one question through vector, BM25 and cross-encoder reranking at once. Comparable 0–1 scores, per-strategy latency, and which chunks the strategies agree on. |
| **Link graph** | Every crawled page as a node, internal links as edges, coloured by link distance from the seed page and sized by how many chunks it contributed. |
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
4. **Generate** — In *quick answer* mode the numbered chunks go to the model
   once. In *research* mode the model calls tools (`search_site`,
   `read_page`, `list_pages`, `compare_retrieval`, plus any MCP tools) in a
   loop until it can answer. Either way a session-wide citation ledger keeps
   `[n]` pointing at the same chunk for the whole chat.
5. **Check** — The grounding meter scores the answer; follow-up questions are
   suggested; everything (including each tool call) is stored in SQLite so the
   chat replays exactly.

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
ANTHROPIC_API_KEY="sk-ant-..."     # Claude Opus / Sonnet / Haiku 5.5
OPENAI_API_KEY="sk-..."
# Any OpenAI-compatible server, e.g. LM Studio:
OPENAI_COMPATIBLE_BASE_URL="http://localhost:1234/v1"
```

Every provider with a key (or a running Ollama) is offered in the model
picker; pick a default under **Settings → Models**. `GET /models` reports
which providers are usable right now and why one isn't, so a missing key or a
stopped Ollama shows up immediately instead of as an error at query time.

For research mode, use a model that supports tool calling (all the hosted
ones, and Ollama models such as `qwen3` or `llama3.1`). Models without it
answer in quick mode automatically.

### 3. Run it

```bash
uv run uvicorn server:app --reload --port 8000    # API on :8000
cd frontend && npm install && npm run dev         # UI on :5173
```

Open <http://localhost:5173>, click **Add a site**, and point it at a docs
site. Press <kbd>⌘K</kbd> / <kbd>Ctrl K</kbd> anywhere to search chats,
sites and past answers.

---

## Terminal

```bash
uv run main.py tui
```

A full-screen chat with sites and chats in a sidebar, streamed answers with
collapsible reasoning and inline tool calls, and the sources of the latest
answer on the right. It runs everything in-process, so no API server is
needed.

| Key | Action | | Command | Action |
|---|---|---|---|---|
| <kbd>Enter</kbd> | send | | `/mode rag\|agent` | quick answer or research |
| <kbd>Esc</kbd> | stop answering | | `/model provider:model` | switch model |
| <kbd>Ctrl N</kbd> | new chat | | `/site <name\|all>` | which sites to search |
| <kbd>Ctrl O</kbd> | pick a model | | `/crawl <url> [site]` | index a page or site |
| <kbd>Ctrl T</kbd> | toggle research | | `/think off\|on\|high` | reasoning |
| <kbd>Ctrl R</kbd> | retry | | `/search <words>` | search past chats |
| <kbd>Ctrl S</kbd> | export Markdown | | `/fork`, `/rename`, `/delete` | manage the chat |
| <kbd>F1</kbd> | help | | `/engine`, `/topk` | retrieval settings |

### One-off commands

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

## MCP

### Use your sites from Claude Desktop, Claude Code or Cursor

AskTheSite is an MCP server with the tools `list_workspaces`, `search_site`,
`read_page`, `list_pages`, `compare_retrieval` and `ask` (a full cited answer),
plus each site's page list as a resource.

Over stdio, add this to your client's MCP config:

```json
{
  "mcpServers": {
    "askthesite": {
      "command": "uv",
      "args": ["--directory", "/path/to/AskTheSite", "run", "main.py", "mcp"]
    }
  }
}
```

With Claude Code: `claude mcp add askthesite -- uv --directory /path/to/AskTheSite run main.py mcp`.

When the API is running, the same server is also at
`http://localhost:8000/mcp` (Streamable HTTP). Behind a proxy, list the host
in `MCP_ALLOWED_HOSTS`.

### Give the agent other MCP servers' tools

Under **Settings → Connections**, add a local command (for example
`npx -y @modelcontextprotocol/server-everything`) or a remote URL with
headers. Connected servers' tools appear in research mode as
`mcp__<server>__<tool>`, and can be switched off individually under
**Settings → Tools**. Secrets in env vars and headers are never sent back to
the browser.

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
| `POST` | `/workspaces/{id}/query` | One-off answer with citations (no memory) |
| `POST` | `/workspaces/{id}/query/stream` | SSE: `sources` → `thinking`/`token` → `done` |
| `POST` | `/workspaces/{id}/retrieval/compare` | All three strategies at once |
| `POST`/`GET` | `/sessions` | Create or list chats (`?workspace_id=`) |
| `GET`/`PATCH`/`DELETE` | `/sessions/{id}` | A chat with its turns; rename, pin, change model or mode |
| `POST` | `/sessions/{id}/chat/stream` | Ask in a chat (SSE, see below); `replace_turn_id` to edit or retry |
| `POST` | `/sessions/{id}/cancel` | Stop the running answer |
| `POST` | `/sessions/{id}/fork` | Duplicate a chat, optionally up to one turn |
| `GET` | `/sessions/{id}/export?format=markdown\|json` | Download a chat |
| `GET` | `/sessions/search?q=` | Full-text search across chats |
| `POST` | `/messages/{id}/feedback` | Thumbs up/down |
| `POST`/`PATCH`/`DELETE` | `/models[/{provider}/{model}]` | Add, show/hide, or set the default model |
| `GET`/`PATCH` | `/tools[/{name}]` | The agent's tools and their on/off switches |
| `GET`/`POST`/`PATCH`/`DELETE` | `/mcp/servers[/{id}]` | External MCP servers; `/test` to try one |
| — | `/mcp` | AskTheSite's own MCP server (Streamable HTTP) |
| `GET` | `/jobs`, `/jobs/{id}` | Job status |
| `GET` | `/jobs/{id}/events` | SSE progress for a running job |

A chat stream emits `turn`, then any of `thinking`, `token`, `tool_call`,
`tool_result`, `sources`, `usage`, `notice`, then `answer`, `grounding`,
`followups` and finally `done` (or `error`):

```bash
curl -N -X POST localhost:8000/sessions/<id>/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"How do I install it?","mode":"agent"}'
```

Set `API_TOKEN` to require `Authorization: Bearer <token>` on every call
except `/health` and the docs.

---

## Project layout

```
AskTheSite/
├── app/
│   ├── agent/        # The harness: turn loop, tools, citation ledger, grounding
│   ├── api/          # FastAPI routers, one per area
│   ├── catalog/      # SQLite with versioned migrations: sites, jobs, chats, settings
│   ├── crawler/      # Crawl4AI wrapper, page front-matter, link manifest
│   ├── embeddings/   # Embedding model
│   ├── index/        # Chroma index + scored retrieval (retrieval.py)
│   ├── ingestion/    # Header-aware chunking with source metadata
│   ├── jobs/         # Background job runner with SSE progress
│   ├── llm/          # Providers, model specs, streaming thinking and tool calls
│   ├── mcp/          # MCP server (our tools) and client (other servers' tools)
│   ├── runtime/      # Cached embedding model, cross-encoder, BM25, stores
│   ├── services/     # Site and chat orchestration
│   ├── storage/      # Vector store backends (Chroma, Qdrant, Mongo)
│   ├── tui/          # Textual terminal app
│   ├── config.py     # All settings, one place
│   └── main.py       # RAGAgent: one-off retrieve → cite → generate
├── frontend/         # React 19 + Vite + Tailwind v4
├── tests/            # pytest, offline via a fake LLM provider
├── main.py           # CLI: crawl, ask, compare, tui, mcp
└── server.py         # Builds the FastAPI app
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

The suite is fully offline: a fake LLM provider (which also plays the agent,
calling `search_site` before it answers) is registered through the same
factory the real ones use, and every test runs against a temporary storage
root, so it never touches your real index. It covers the harness, sessions,
migrations, both MCP directions (including a real stdio round trip) and the
terminal app through Textual's headless pilot.

---

## Configuration

All settings live in `.env` (see `.env.example`). The most useful ones:

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `opensource` | Default provider until you pick one in Settings: `opensource` (Ollama), `anthropic`, `openai`, `openai_compatible` |
| `LLM_MODEL` | `qwen3.5:4b-mlx` | Default Ollama model |
| `OPENAI_COMPATIBLE_BASE_URL` | — | Any OpenAI-compatible server |
| `LLM_THINKING` / `LLM_EFFORT` | `true` / — | Ask for visible reasoning; `low`, `medium` or `high` effort |
| `AGENT_MAX_STEPS` | `8` | Model calls per research answer |
| `AGENT_ALLOW_FETCH` | `false` | Let the agent fetch live pages outside the index |
| `AGENT_FOLLOWUPS` | `true` | Suggest follow-up questions |
| `API_TOKEN` | — | Require a bearer token on the API |
| `MCP_ALLOWED_HOSTS` | localhost | Hosts `/mcp` accepts behind a proxy |
| `PERSISTENT_STORAGE` | `./storage/cache` | Chroma index location |
| `WORKSPACE_ROOT` | `./workspaces` | Crawled markdown, per workspace |
| `CRAWL_MAX_PAGES` | `100` | Default page cap for a site crawl |
| `CRAWL_HEADLESS` | `true` | Must stay true outside a desktop session |
| `MAX_CONCURRENT_JOBS` | `2` | Parallel crawl/ingest jobs |

---

## License

MIT
