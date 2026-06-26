# Synapse AI Agent — Frontend

A no-build-step single-page application that drives the research agent through
its FastAPI contract: submit a query, review the generated plan (HITL),
watch the pipeline run, and read the final report with grounded citations.

## Requirements

- A running Synapse API backend (see root `README.md` for how to start it).
- A modern browser (Chrome 90+, Firefox 88+, Safari 15+, Edge 90+) for
  `type="module"` ES-module support and `EventSource` (SSE).
- No Node.js, no build step, no `package.json`.

## How to run

### 1. Start the API backend

From the repository root:

```bash
source venv/bin/activate
python -m api.app
```

The API listens on `http://localhost:8000` by default (configured in
`config/configuration.yaml` under `api.host` / `api.port`).

### 2. Serve the frontend

The simplest way is Python's built-in HTTP server from the `frontend/` directory:

```bash
cd /path/to/synapse_AI_Agent/frontend
python -m http.server 5173
```

Then open `http://localhost:5173` in your browser.

Any static file server works (nginx, Caddy, VS Code Live Server, etc.).
The file must be served over HTTP (not opened as `file://`) because ES modules
require a server origin.

### 3. Configure the API base URL

The API base URL is set in one place:

```
frontend/js/api.js  —  line:  export const API_BASE = 'http://localhost:8000';
```

Change this constant if your backend runs on a different host or port.

### 4. CORS note

`config/configuration.yaml` currently has:

```yaml
api:
  cors_origins:
    - "*"
```

This wildcard allows requests from any origin and works for local development.
For production deployments, replace `"*"` with the exact origin of the
frontend server, e.g.:

```yaml
api:
  cors_origins:
    - "http://localhost:5173"
    - "https://yourapp.example.com"
```

Do not change `config/configuration.yaml` to add a frontend origin unless
you are deploying to a fixed domain — the wildcard is correct for local dev.

## User flow

1. **Query entry** — type a research question (required) and optional advanced
   controls (max retrieval iterations, max revise iterations). Click
   "Start Research" to call `POST /runs`.

2. **Plan review (HITL)** — the agent pauses after scoping and presents
   audience / length / tone / sections. Three choices:
   - **Approve** — graph proceeds to retrieval + writing.
   - **Edit** — modify any field or section in-line; submitting sends the
     edited plan back and the agent re-scopes (may loop several times).
   - **Reject** — agent discards the plan and generates a new one from scratch
     (the re-interrupt loop continues until you approve).

3. **Progress** — while `POST /runs/{id}/resume` is in flight the pipeline
   stage list animates. If the server supports concurrent SSE, the checkpoint
   log updates live; otherwise it populates after the run completes.

4. **Report** — final report rendered section-by-section with grounding badges,
   revision counts, inline citation links, and a collapsible sources panel.
   A low-confidence banner appears when the source grader exited at its cap.

## File map

```
frontend/
├── index.html           Shell HTML; loads styles.css and js/app.js
├── styles.css           All styles (custom properties, no framework)
├── FRONTEND_NOTES.md    Component map, state strategy, API contract mapping
└── js/
    ├── api.js           All fetch/EventSource calls (change API_BASE here)
    ├── state.js         Minimal reactive store (pub/sub)
    ├── utils.js         HTML-escape helper (esc) + error formatter
    ├── markdown.js      Lightweight Markdown -> HTML renderer
    ├── queryView.js     Query entry form
    ├── planView.js      HITL plan review + edit
    ├── progressView.js  Pipeline progress (SSE events + animated fallback)
    ├── reportView.js    Final report, sections, low-confidence banner, sources
    └── app.js           State machine, view dispatcher, action handlers
```
