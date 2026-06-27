# DEPLOY_NOTES — synapse-ai-agent

## Deploy path

### Local (Docker)

```bash
# 1. Build the image (multi-stage; BuildKit recommended)
DOCKER_BUILDKIT=1 docker build -t synapse-ai-agent:latest .

# 2. Run with secrets injected via --env-file (never bake keys into the image)
docker run \
  --env-file .env \
  -p 8000:8000 \
  synapse-ai-agent:latest

# 3. Verify liveness
curl http://localhost:8000/healthz     # expects {"status": "ok"}
open http://localhost:8000/docs        # OpenAPI UI
```

### Local (without Docker)

```bash
uv venv venv --python 3.13
uv pip install --python venv/bin/python -e '.[test]'
# Copy and fill in secrets
cp .env.example .env && $EDITOR .env
venv/bin/python -m api.app
```

### Production (Docker Compose example)

```yaml
services:
  api:
    image: ghcr.io/<owner>/synapse-ai-agent:latest   # replace <owner>
    ports:
      - "8000:8000"
    env_file:
      - .env          # never commit this file; inject from secrets manager
    volumes:
      - synapse-data:/app/data   # durable SQLite persistence (see below)
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c",
             "import urllib.request, sys; r = urllib.request.urlopen('http://localhost:8000/healthz', timeout=8); sys.exit(0 if r.status == 200 else 1)"]
      interval: 30s
      timeout: 10s
      start_period: 40s
      retries: 3

volumes:
  synapse-data:
```

---

## Secrets flow

| Secret | Where it comes from | Used by |
|---|---|---|
| `OPENAI_API_KEY` | Runtime env / secrets manager | LLM calls when `LLM_PROVIDER=openai` |
| `GROQ_API_KEY` | Runtime env / secrets manager | LLM calls when `LLM_PROVIDER=groq` |
| `GOOGLE_API_KEY` | Runtime env / secrets manager | Embedding model (always required) |
| `ASTRA_DB_APPLICATION_TOKEN` | Runtime env / secrets manager | AstraDB retriever (optional) |
| `TAVILY_API_KEY` | Runtime env / secrets manager | Tavily web-search tool (optional) |
| `LANGCHAIN_API_KEY` | Runtime env / secrets manager | LangSmith tracing (optional) |
| `GITHUB_TOKEN` | Injected automatically by GitHub Actions | GHCR push (no manual setup needed) |

**Rules enforced by this repo:**
- `.env` is in `.gitignore` and must never be committed. A committed secret is a stop-the-line failure.
- The Dockerfile contains no `ARG` or `ENV` directives that accept key values at build time.
- `.env.example` ships only placeholder values (never real keys).
- CI never receives provider API keys (unit tests are fully offline; live evals are opt-in via `RUN_LIVE_EVALS=1`).

**No additional GitHub repository secrets are required for GHCR** — the workflow uses the built-in
`GITHUB_TOKEN` with `permissions: packages: write`.

---

## Persistence durability

The checkpointer is selected by `persistence.db_path` in `config/configuration.yaml`:

| Setting | Behaviour | Durability |
|---|---|---|
| `":memory:"` (default) | `MemorySaver` — in-process only | Lost on every restart |
| `"data/synapse.db"` | `SqliteSaver` — file on disk | Durable if `/app/data` is a named volume |

To enable durable persistence:

1. Edit `config/configuration.yaml`:
   ```yaml
   persistence:
     db_path: "data/synapse.db"
   ```
2. Mount a named Docker volume at `/app/data` (see the Compose example above).
3. The `/app/data` directory is pre-created in the image and owned by the `appuser`
   non-root user; no `chown` step is needed at runtime.

**Without a volume** the SQLite file lives inside the container's writable layer and is
destroyed on `docker rm`. The named volume survives `docker stop`, `docker rm`, image
upgrades, and redeploys — as long as the volume is not explicitly deleted.

---

## CI/CD pipeline

File: `.github/workflows/ci.yml`

```
push / PR to master
      |
      v
  [test job] — ubuntu-latest, Python 3.13
      |  uv pip install --system -e '.[test]'
      |  pytest tests/unit -q        <- offline only; no API keys needed
      |  RUN_LIVE_EVALS=""           <- live evals explicitly suppressed
      |
      v (only if test passes)
  [docker-build job]
      |  docker/setup-buildx-action   <- enables BuildKit
      |  Compute lowercase GHCR image name from github.repository
      |
      +-- PR branch:
      |     docker/build-push-action (push=false, cache=type=gha)
      |     Build only — no login, no push
      |
      +-- master push:
            docker/login-action (registry=ghcr.io, password=GITHUB_TOKEN)
            docker/build-push-action (push=true, cache=type=gha,mode=max)
            Tags: ghcr.io/<owner>/synapse-ai-agent:latest
                  ghcr.io/<owner>/synapse-ai-agent:sha-<full-sha>
```

**Caching:** BuildKit layer cache is stored in GitHub Actions cache (`type=gha`). The uv
download cache is stored separately via `actions/cache` keyed on `pyproject.toml` hash,
so dependency downloads are skipped on subsequent runs when the dependency set is unchanged.

**What is NOT run in CI:**
- Live eval harness (`evals/harness.py`) — requires `RUN_LIVE_EVALS=1` and real provider
  API keys. Run manually against staging:
  ```bash
  RUN_LIVE_EVALS=1 python -m evals.harness --provider groq
  ```

---

## Observability

- **Structured logs** — `structlog` emits JSON to stdout (captured by the container runtime)
  and to a timestamped file under `/app/logs/`. Forward stdout to your log aggregator
  (CloudWatch, Datadog, Loki, etc.).
- **Key fields in every log line** — `event`, `timestamp`, `level`, `file`, `line`.
- **Grader loop telemetry** — look for `retrieval_iteration` and `revise_iteration` fields
  in node log lines to track how many loop iterations each run consumed.
- **Token usage** — LangChain / LangGraph emit token-count metadata on each LLM call;
  set `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` to send traces to LangSmith for
  per-run token accounting.
- **Health endpoint** — `GET /healthz` returns `{"status": "ok"}` and is wired to both
  the Docker `HEALTHCHECK` instruction and to container orchestrator liveness probes.

---

## Checklist

- [ ] `.env` is **not** committed to git (`git ls-files .env` returns nothing)
- [ ] `.env.example` is committed with placeholder values only
- [ ] `Dockerfile` builds successfully (`DOCKER_BUILDKIT=1 docker build -t synapse-ai-agent:latest .`)
- [ ] Container starts and `/healthz` returns 200 (`docker run --env-file .env -p 8000:8000 synapse-ai-agent:latest`)
- [ ] Container runs as non-root user (verify: `docker exec <id> id` shows `uid=1000(appuser)`)
- [ ] GitHub Actions CI passes on a test push to master (unit tests green, Docker image built and pushed to GHCR)
- [ ] GHCR package visibility set appropriately (public or private) in GitHub repo settings
- [ ] Named volume mounted at `/app/data` **if** durable SQLite persistence is required (otherwise `:memory:` default is acceptable)
- [ ] `persistence.db_path` in `config/configuration.yaml` set to `"data/synapse.db"` when using the volume
- [ ] Log output forwarded to an aggregator in production
- [ ] LangSmith tracing configured if per-run token accounting is required (`LANGCHAIN_TRACING_V2=true`, `LANGCHAIN_API_KEY`)
- [ ] API keys rotated if they were ever visible in plaintext outside of a secrets manager
