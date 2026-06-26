# Frontend Notes

## Component map

| File | Responsibility |
|------|---------------|
| `index.html` | Page shell: header with health-status indicator, `<main id="app">` mount point, footer with API base URL, two `<script type="module">` tags. |
| `styles.css` | Full design system via CSS custom properties. No framework. WCAG AA contrast on all text/background pairs. |
| `js/api.js` | Single file for all backend communication. Exports `startRun`, `resumeRun`, `getRunStatus`, `streamRun`, `healthCheck`, and `ApiError`. `API_BASE` constant is the only place the backend URL appears. |
| `js/state.js` | `createStore(initialState)` — minimal pub/sub reactive store. Returns `getState / setState / subscribe`. `setState` accepts a plain object or an updater function `(prev) => patch`. |
| `js/utils.js` | `esc(str)` — HTML-escapes untrusted values before injection into innerHTML. `formatError(err)` — normalises ApiError / Error / plain object into `{ message, detail }` for display. |
| `js/markdown.js` | `renderMarkdown(text)` — escapes HTML first, then applies line-by-line Markdown: ATX headings, bold/italic/inline-code, links, unordered/ordered lists, horizontal rules, paragraphs. No external dependency. |
| `js/queryView.js` | Query entry form. Maps form values to `RunRequest` DTO. Passes `null` (not empty string) for optional integer fields when blank. |
| `js/planView.js` | Two-mode view: `review` (read-only plan display) and `edit` (in-line editor). `snapshotDOM()` reads current input values back into `editState` before every mutation. Builds `edited_plan` matching `PlanDTO` shape on submit. |
| `js/progressView.js` | Mounts the stage list and checkpoint log. Returns `{ cleanup }` so app.js can clear the auto-cycle `setInterval`. `updateProgressView` does incremental DOM updates for arriving SSE events. |
| `js/reportView.js` | Renders the low-confidence banner, section-by-section report (with grounding/revision badges and per-section citation links), assembled-report fallback, and sources panel with smooth-scroll citation anchors. |
| `js/app.js` | State machine, view dispatcher, action handlers. Manages SSE connection lifecycle (`sseConnection`). Calls `cleanup()` on current view before re-rendering. |

## State strategy

```
{
  screen: 'idle' | 'submitting' | 'awaiting_plan_approval' | 'resuming' | 'completed' | 'error',
  threadId: string | null,
  query: string | null,
  plan: PlanDTO | null,
  interruptPayload: object | null,
  checkpoints: CheckpointEvent[],   // SSE events (may be empty)
  report: string | null,
  finalAnswer: string | null,       // JSON-serialised terminal payload
  sections: SectionDTO[] | null,
  sources: SourceDTO[] | null,
  lowConfidence: boolean | null,
  error: unknown,
}
```

Transitions:
- `idle → submitting` when the query form is submitted.
- `submitting → awaiting_plan_approval` when `POST /runs` returns `status:"awaiting_plan_approval"`.
- `awaiting_plan_approval → resuming` when the user clicks Approve / Edit / Reject.
- `resuming → awaiting_plan_approval` when `POST /resume` returns `status:"awaiting_plan_approval"` (re-interrupt from edit/reject path).
- `resuming → completed` when `POST /resume` returns `status:"completed"`.
- Any state → `error` on fetch failure.
- `error → idle` via "Start Over" button.

The store's `subscribe(render)` call means every `setState` triggers a full view re-render.  View-local mutable state (e.g. edit mode in `planView`) lives inside the mount function's closure, not in the store, so it survives re-renders only within the same mount call.

## API contract mapping

### `POST /runs`  (startRun)
- Request body: `RunRequest` — `query` required; `max_retrieval_iterations` and `max_revise_iterations` only sent when non-null (backend reads its own defaults from YAML otherwise).
- Response: `RunResponse` — `thread_id`, `status`, `plan`, `interrupt_payload`.
- Frontend uses: `thread_id` (stored in state), `status` (drives state transition), `plan` (rendered in planView), `interrupt_payload.query` and `interrupt_payload.instructions` (shown in planView header).

### `POST /runs/{thread_id}/resume`  (resumeRun)
- Request body: `ResumeRequest` — `action: "approve"|"edit"|"reject"`, `edited_plan` (PlanDTO shape) only when `action === "edit"`.
- Response: `ResumeResponse` — `thread_id`, `status`, plus `plan` + `interrupt_payload` when re-interrupting, or `report`, `final_answer`, `sections[]`, `low_confidence`, `sources[]`, `plan` when completed.
- Frontend uses: all fields — `sections[].spec_id` is matched against `plan.sections[].id` for ordering; `sections[].cited_source_ids[]` matched against `sources[].id` for citation rendering.

### `GET /runs/{thread_id}/stream`  (streamRun via EventSource)
- Server-sent events, `text/event-stream`, each line `data: {...}\n\n`.
- Three event types: `checkpoint` (normal progress), `done` / `not_found` (terminal), `error` (stream failure).
- `checkpoint` shape: `{ event, thread_id, status, step, node, next[], has_report, has_final_answer, low_confidence }`.
- Frontend uses: `node` (maps to `STAGES[]` for label + stage-list highlight), `step` (checkpoint log column), `status`, `next[]` (shown in log).
- Stream is opened in parallel with the `POST /resume` call. The POST response is always authoritative; SSE is supplemental for progress display.

### `GET /runs/{thread_id}`  (getRunStatus — imported but not currently used in the main flow)
- Available as a polling fallback. Not wired into the main state machine loop because the `POST /resume` call is authoritative. Can be used for recovery if the page reloads mid-run.

### `GET /healthz`  (healthCheck)
- Called once on page load; result updates the header dot + label.

## CORS for local development

`config/configuration.yaml` ships with `cors_origins: ["*"]` which covers all local dev scenarios.  No change is needed.  If the frontend is served from a non-localhost origin in production, add that origin to the YAML list.

## Accessibility notes

- Semantic HTML: `<header role="banner">`, `<main>`, `<footer role="contentinfo">`, `<article>`, `<section aria-labelledby>`, `<aside>`.
- All form inputs have associated `<label for>` elements.
- Error messages use `role="alert"` and `aria-live="assertive"` for immediate screen-reader announcement.
- Progress log uses `role="log"` with `aria-live="polite"`.
- The spinner has `role="status"` with an `aria-label`.
- Plan action buttons are grouped in `role="group"` with `aria-label`.
- Keyboard navigation: all interactive elements reach via Tab; buttons and links have `:focus-visible` ring; confirm dialog on Reject.
- Contrast: all text/background pairs verified against WCAG AA (4.5:1 for normal text, 3:1 for large/bold). Dark slate text on white cards; amber warning uses `#78350f` (amber-900) on `#fef3c7` (amber-100) — ratio ≈ 7:1.
