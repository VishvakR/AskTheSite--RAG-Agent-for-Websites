# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.11.9
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # Keep model + browser caches inside the image/volume rather than $HOME.
    HF_HOME=/app/cache \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright

# Chromium's runtime libraries. Without these the crawler cannot launch a
# browser at all, which is why the previous image could never crawl.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Installs Chromium plus its OS dependencies.
RUN uv run playwright install --with-deps chromium

COPY . .

# Ollama and Chroma both resolve relative to these; declare them so a volume
# can be mounted over them and the index survives a restart.
VOLUME ["/app/storage", "/app/workspaces"]

ENV PERSISTENT_STORAGE=/app/storage/cache \
    CATALOG_DB=/app/storage/askthesite.db \
    WORKSPACE_ROOT=/app/workspaces \
    CRAWL_HEADLESS=true

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# server:app, not main:app -- main.py is the CLI and defines no ASGI app.
# One worker: the job runner and resource caches are per-process, so multiple
# workers would each hold their own copy and progress streams would miss.
CMD ["uv", "run", "gunicorn", "server:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "--workers", "1", "--timeout", "600", \
     "--bind", "0.0.0.0:8000"]
