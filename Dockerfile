# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# synapse-ai-agent — FastAPI backend container  (multi-stage build)
# ---------------------------------------------------------------------------
# Build:  docker build -t synapse-ai-agent:latest .
# Run:    docker run --env-file .env -p 8000:8000 synapse-ai-agent:latest
#
# Runtime secrets MUST be injected via --env-file or -e flags.
# NEVER bake API keys into this image or pass them as build args.
# ---------------------------------------------------------------------------

# ============================================================================
# Stage 1 — builder
# Install uv and lay down all runtime dependencies into an isolated venv.
# The uv download cache is mounted as a BuildKit cache so it is reused across
# local rebuilds and in CI (when paired with type=gha BuildKit cache).
# ============================================================================
FROM python:3.13-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy the full source tree (excluding what .dockerignore omits).
COPY . .

# Create an isolated venv and install runtime dependencies only (no test extras).
#
# IMPORTANT — editable install (-e .) is required here.
# utils/config_loader.py resolves the project root via:
#     Path(__file__).resolve().parents[1]
# A non-editable install would place that file inside site-packages, making
# the path calculation wrong.  Editable install leaves __file__ pointing at
# /app/utils/config_loader.py so .parents[1] == /app, where configuration.yaml
# lives.  The venv's .pth file keeps this reference intact in the runtime stage.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python -e .

# ============================================================================
# Stage 2 — runtime
# Minimal image: only the venv and source, no build tooling.
# ============================================================================
FROM python:3.13-slim AS runtime

# Copy the venv produced by the builder (preserves the editable .pth pointer
# to /app, which is where the source lands in the next COPY step).
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Copy the application source to the path the editable .pth file references.
COPY --from=builder /app .

# Pre-create runtime directories so the app can write on first boot without
# needing root at runtime.
#   logs/ — structlog writes a timestamped JSON log file here (os.getcwd()/logs)
#   data/ — mount a named Docker volume here to enable durable SQLite persistence
#            (set persistence.db_path: "data/synapse.db" in configuration.yaml)
RUN groupadd -r appgroup && \
    useradd -r -u 1000 -g appgroup -s /sbin/nologin appuser && \
    mkdir -p /app/logs /app/data && \
    chown -R appuser:appgroup /app/logs /app/data

USER appuser

# Put the venv on PATH so `python` and `uvicorn` resolve to the venv binaries.
ENV PATH="/opt/venv/bin:$PATH"

# The FastAPI / uvicorn server binds to 0.0.0.0:8000
# (controlled by api.host / api.port in config/configuration.yaml)
EXPOSE 8000

# Liveness probe — uses the stdlib urllib so no curl/wget is needed in the image.
# start-period gives the graph time to compile at startup before the probe fires.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c \
    "import urllib.request, sys; \
     r = urllib.request.urlopen('http://localhost:8000/healthz', timeout=8); \
     sys.exit(0 if r.status == 200 else 1)" || exit 1

# ---------------------------------------------------------------------------
# Required runtime environment variables (inject via --env-file or -e, never bake):
#
#   GOOGLE_API_KEY               — always required (embedding model is Google)
#   OPENAI_API_KEY               — required when LLM_PROVIDER=openai (default)
#   GROQ_API_KEY                 — required when LLM_PROVIDER=groq
#
# Optional:
#   LLM_PROVIDER                 — openai | google | groq  (default: openai)
#   ASTRA_DB_API_ENDPOINT        — AstraDB vector store endpoint
#   ASTRA_DB_APPLICATION_TOKEN   — AstraDB auth token
#   ASTRA_DB_KEYSPACE            — AstraDB keyspace name
#   TAVILY_API_KEY               — Tavily web-search tool
#   CONFIG_PATH                  — override config/configuration.yaml location
#   LANGCHAIN_TRACING_V2=true    — enable LangSmith tracing
#   LANGCHAIN_API_KEY            — LangSmith API key (required if tracing enabled)
# ---------------------------------------------------------------------------
CMD ["python", "-m", "api.app"]
