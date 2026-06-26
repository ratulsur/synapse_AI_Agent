# Synapse AI Agent

A research and analyst agent built on [LangGraph](https://langchain-ai.github.io/langgraph/) and
[LangChain](https://www.langchain.com/), with pluggable LLM providers and a configuration-driven
model layer. Given a research question, it scopes a report plan, pauses for human approval, retrieves
evidence from real sources, drafts the report section by section, grades each section against its
sources, and assembles a grounded, citation-backed report.

## Pipeline

```
create_analyst → scope_plan → human_in_the_loop ──approve──▶ query_router
                      ▲              │                              │
                      └──revise──────┘                             ▼
                                                          retrieval_evidence  (tool loop +
                                                                  │            source-grader retry)
                                                                  ▼
   final_answer ◀── assemble_report ◀──grounded── grounding_grader ◀── section_drafting ◀── write
                                                          │              (parallel writers)
                                                          └──ungrounded──▶ revise_section ─┘
```

- **Human-in-the-loop plan approval** — the graph interrupts after planning so you can approve, edit,
  or reject the report plan before any retrieval happens.
- **Tool-augmented retrieval with a self-correcting loop** — a ReAct agent retrieves from web, Wikipedia /
  Wikivoyage, and arXiv (plus optional external-API and MCP tools), bounded by a source-grader that can
  reformulate, widen, or reroute the search when evidence is weak.
- **Per-section grounding** — every drafted section is graded against the sources it cites; only failing
  sections are revised, so already-grounded prose is never regressed.
- **Pluggable LLM providers** — switch between OpenAI, Google Gemini, and Groq at runtime via one env var.
- **Durable runs** — SQLite-backed LangGraph checkpointing lets runs survive restarts and resume from the
  approval interrupt.
- **Two front doors** — a FastAPI backend (run / resume / status / SSE stream) and a dependency-free static
  web UI, plus a standalone single-LLM CLI chat agent.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the authoritative graph topology, state schema, and feedback-loop
contracts.

## Requirements

- Python **3.13+**
- [uv](https://docs.astral.sh/uv/) for environment and dependency management
- API keys for the provider(s) you intend to use (OpenAI, Google, and/or Groq)

## Installation

```bash
git clone https://github.com/ratulsur/synapse_AI_Agent.git
cd synapse_AI_Agent

# Create the virtual environment (Python 3.13) and install (with test extras)
uv venv venv --python 3.13
uv pip install --python venv/bin/python -e '.[test]'
```

## Configuration

### Environment variables

Create a `.env` file in the project root (it is git-ignored):

```dotenv
# Provider API keys (set the ones you use)
OPENAI_API_KEY=your-openai-key
GOOGLE_API_KEY=your-google-key
GROQ_API_KEY=your-groq-key

# Selects which LLM provider to load (defaults to "openai")
LLM_PROVIDER=openai

# Optional: override the config file location
# CONFIG_PATH=/path/to/configuration.yaml
```

| Variable         | Required        | Description                                                                                        |
| ---------------- | --------------- | -------------------------------------------------------------------------------------------------- |
| `OPENAI_API_KEY` | If using OpenAI | API key for OpenAI models.                                                                         |
| `GOOGLE_API_KEY` | If using Google | API key for Gemini and the embedding model.                                                        |
| `GROQ_API_KEY`   | If using Groq   | API key for Groq models.                                                                            |
| `LLM_PROVIDER`   | No              | One of `openai`, `google`, `groq`. Must match a key under `llm` in the YAML. Defaults to `openai`. |
| `CONFIG_PATH`    | No              | Explicit path to the configuration file. Overrides the default location.                           |

### Configuration file

All settings live in [`config/configuration.yaml`](config/configuration.yaml): the three LLM provider blocks,
the fixed Google embedding model, graph loop caps (`agent.max_retrieval_iterations`,
`agent.max_revise_iterations`), the routable `domains`, per-tool tunables (`tools.*`), persistence
(`persistence.db_path` — `":memory:"` by default; set a file path to enable durable SQLite checkpointing),
and the API server `host`/`port`/`cors_origins`. The embedding provider is fixed to Google; only the LLM
provider is switchable via `LLM_PROVIDER`.

## Usage

### Web app (backend + UI)

```bash
# 1. Start the API server (builds the graph once; serves on 0.0.0.0:8000)
venv/bin/python -m api.app           # http://localhost:8000  — /docs for OpenAPI, /healthz for liveness

# 2. Serve the static frontend (points at localhost:8000)
cd frontend && python3 -m http.server 5500   # open http://localhost:5500/index.html
```

The UI submits a query, displays the generated plan for approval/edit/reject, streams progress, and renders
the final report with per-section citations and a sources panel.

### API directly

```bash
# Start a run — returns a thread_id and pauses at the plan-approval interrupt
curl -s -X POST http://localhost:8000/runs \
  -H 'Content-Type: application/json' \
  -d '{"query":"What are recent advances in retrieval-augmented generation?"}'

# Approve the plan to run the pipeline to completion
curl -s -X POST http://localhost:8000/runs/<thread_id>/resume \
  -H 'Content-Type: application/json' \
  -d '{"action":"approve"}'
```

Endpoints: `POST /runs`, `POST /runs/{thread_id}/resume` (`approve` / `edit` / `reject`),
`GET /runs/{thread_id}`, `GET /runs/{thread_id}/stream` (SSE), `GET /healthz`.

### Command-line chat agent

`main.py` is a standalone single-LLM chat assistant (not the report pipeline):

```bash
venv/bin/python main.py --prompt "Summarize recent advances in RAG"
venv/bin/python main.py                       # interactive REPL
venv/bin/python main.py --provider groq       # override LLM_PROVIDER for this run
venv/bin/python main.py --show-config         # print the resolved configuration and exit
```

## Development

```bash
# Tests (offline; any network call times out by design)
venv/bin/python -m pytest                      # full suite
venv/bin/python -m pytest tests/unit/test_routers.py::test_name   # a single test

# Graded eval harness — LIVE, opt-in (real LLM + search calls; default provider groq)
RUN_LIVE_EVALS=1 venv/bin/python -m evals.harness --provider groq
```

Run everything from the **repo root** as modules (`python -m pkg.mod`); imports are absolute from the root.

## Adding a new LLM provider

1. Add a provider block under `llm` in `config/configuration.yaml`.
2. Add a matching branch in `ModelLoader.load_llm()` in `utils/model_loader.py`.
3. Add any new API key to `ApiKeyManager`.

## License

Released under the [MIT License](LICENSE).
