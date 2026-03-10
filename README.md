# AskTheSite — RAG Agent for Websites

A Retrieval-Augmented Generation (RAG) pipeline that crawls websites, ingests content into vector stores, and enables question-answering over the crawled data using LLMs.

## Features

- **Web Crawling** — Crawl single pages or entire websites with BFS, sitemap support, and `robots.txt` compliance
- **Multiple Vector Stores** — Choose between MongoDB Atlas, Qdrant, or ChromaDB for document storage
- **LLM Providers** — Supports OpenAI and open-source models (via Ollama)
- **Document Ingestion** — Markdown-aware text splitting with optional LLM-generated metadata

## Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [Ollama](https://ollama.ai/) (for open-source models)

### Installation

```bash
# Clone the repository
git clone https://github.com/VishvakR/AskTheSite--RAG-Agent-for-Websites.git
cd AskTheSite--RAG-Agent-for-Websites

# Install dependencies with uv
uv sync

# Or with pip
pip install -e .
```

### Environment Variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `PERSISTENT_STORAGE` | Local path for ChromaDB persistence |
| `MONGODB_URI` | MongoDB Atlas connection string |
| `QDRANT_URL` | Qdrant Cloud cluster URL |
| `QDRANT_API_KEY` | Qdrant API key |

## Usage

```python
import asyncio
from app.crawler import WebCrawler
from app.storage import StoreManager
from app.ingestion.parsing import Documents

async def main():
    # 1. Crawl a website
    crawler = WebCrawler()
    await crawler.get_page_data(
        url="https://example.com",
        folder="output",
        filename="example",
    )

    # 2. Ingest documents
    docs = Documents(input_files="output/").create_nodes()

    # 3. Store in vector DB
    storage = StoreManager.get_or_create(
        store_type="mongodb",  # or "qdrantdb", "chromadb"
        namespace="my_collection",
    )
    storage.get_vector_store().add_documents(docs)

asyncio.run(main())
```

## Project Structure

```
├── app/
│   ├── crawler/        # Web crawling with BFS, sitemap, robots.txt
│   ├── embeddings/     # HuggingFace embedding models
│   ├── ingestion/      # Document loading and text splitting
│   ├── llm/            # LLM providers (OpenAI, Ollama)
│   ├── storage/        # Vector store providers (MongoDB, Qdrant, Chroma)
│   └── logger.py       # Centralized logging config
├── main.py             # Entry point
├── .env.example        # Environment variable template
└── pyproject.toml      # Project dependencies
```

## License

MIT
