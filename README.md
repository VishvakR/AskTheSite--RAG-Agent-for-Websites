# AskTheSite

Point it at any website, ask a question, get an answer. That's the idea.

AskTheSite crawls a target URL, converts the page content into a searchable vector index, and runs a retrieval-augmented generation pipeline on top of it. You end up with a local "Q&A bot" that actually knows the content of the site — not just what the LLM was trained on.

---

## How it works

1. **Crawl** — [Crawl4AI](https://github.com/unclecode/crawl4ai) fetches the target page(s) and extracts clean markdown from the HTML.
2. **Ingest** — The markdown is chunked, embedded with a sentence-transformer model, and stored in a local [ChromaDB](https://www.trychroma.com/) collection.
3. **Retrieve** — When you ask a question, the most relevant chunks are pulled back using one of three retrieval strategies (see below).
4. **Generate** — The retrieved context is stuffed into a prompt and sent to an LLM (Ollama or OpenAI) which writes the final answer.

Everything runs locally by default — no API key required if you have [Ollama](https://ollama.ai/) installed.

---

## Retrieval strategies

You can swap these out via the `query_engine` parameter:

| Strategy | How it works |
|---|---|
| `auto` | Standard cosine-similarity vector search |
| `bm25` | Classic keyword-based BM25 scoring |
| `rerank` | Ensemble of vector + BM25, then a HuggingFace cross-encoder rescores the candidates |

The `rerank` mode generally gives the best results but is slower since it loads a local cross-encoder model (`cross-encoder/ms-marco-MiniLM-L-6-v2` by default).

---

## Project layout

```
AskTheSite/
├── app/
│   ├── crawler/        # Crawl4AI wrapper — fetches pages, extracts markdown
│   ├── embeddings/     # Embedding model management
│   ├── index/
│   │   ├── providers/  # ChromaDB index implementation
│   │   └── retriever/  # auto, bm25, rerank retriever implementations
│   ├── ingestion/      # Document parsing and chunking
│   ├── llm/            # LLM abstraction (Ollama / OpenAI)
│   ├── storage/        # Vector store backends (ChromaDB, Qdrant, MongoDB)
│   └── main.py         # RAGAgent — ties everything together
├── main.py             # CLI entry point (crawl → ingest → query)
├── server.py           # FastAPI server
├── Dockerfile
└── compose.yaml
```

---

## Quickstart

### Prerequisites

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- [Ollama](https://ollama.ai/) running locally with `llama3.1:8b` pulled — or an OpenAI API key

### 1. Clone and install

```bash
git clone https://github.com/VishvakR/AskTheSite.git
cd AskTheSite

uv sync          # or: pip install -e .
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — at minimum set `PERSISTENT_STORAGE` (defaults to `./storage/cache`). The MongoDB and Qdrant values are only needed if you swap the storage backend away from the default ChromaDB.

```env
PERSISTENT_STORAGE="./storage/cache"

# Optional — only if using MongoDB Atlas as the vector store
MONGODB_URI="mongodb+srv://<user>:<pass>@<cluster>.mongodb.net/..."

# Optional — only if using Qdrant Cloud
QDRANT_URL="https://<cluster-id>.cloud.qdrant.io"
QDRANT_API_KEY="your-qdrant-api-key-here"
```

### 3. Pull the LLM (if using Ollama)

```bash
ollama pull llama3.1:8b
```

### 4. Run the demo script

Edit the target URL and demo query at the top of `main.py`, then:

```bash
uv run main.py
```

This crawls the site, builds the index, and prints an answer to the demo query.

---

## API server

A [FastAPI](https://fastapi.tiangolo.com/) server is included if you want to integrate the pipeline into another application or call it from a UI.

### Start the server

```bash
uv run uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```

Interactive docs available at [http://localhost:8000/docs](http://localhost:8000/docs).

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/crawl` | Crawl a URL and save the extracted markdown |
| `POST` | `/ingest` | Parse crawled files and build the vector index |
| `POST` | `/query` | Ask a question against the existing index |
| `POST` | `/pipeline` | Run all three steps in one request |

#### Full pipeline example

```bash
curl -X POST http://localhost:8000/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://docs.crawl4ai.com",
    "query": "What is crawl4ai and how does it work?",
    "query_engine": "rerank",
    "top_k": 5,
    "llm_model_type": "opensource",
    "llm_model_name": "llama3.1:8b"
  }'
```

#### Query only (index already built)

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "What is crawl4ai and how does it work?",
    "query_engine": "auto",
    "top_k": 5
  }'
```

---

## Docker

```bash
docker compose up --build
```

The server starts on port `8000`. The compose file mounts the `storage/` directory so the ChromaDB index persists between container restarts.

---

## LLM options

| `llm_model_type` | `llm_model_name` examples | Notes |
|---|---|---|
| `opensource` | `llama3.1:8b`, `mistral`, `phi3` | Requires Ollama running locally |
| `openai` | `gpt-4o`, `gpt-4o-mini` | Requires `OPENAI_API_KEY` in `.env` |

---

## Observability

The project optionally integrates with [Arize Phoenix](https://phoenix.arize.com/) for tracing the RAG pipeline via OpenTelemetry. Pass a `phoenix_api_key` to `RAGAgent` to enable it — traces are streamed to `llamatrace.com`.

---

## Dependencies

All managed through `pyproject.toml`. Key packages:

- `crawl4ai` — async web crawling with clean markdown extraction
- `langchain` + `langchain-chroma` — RAG orchestration and vector store integration
- `chromadb` — local vector database
- `sentence-transformers` — embedding models
- `rank-bm25` — BM25 keyword retrieval
- `langchain-ollama` / `langchain-openai` — LLM backends
- `fastapi` + `uvicorn` — API server
- `arize-phoenix` + `opentelemetry-sdk` — tracing

---

## License

MIT
