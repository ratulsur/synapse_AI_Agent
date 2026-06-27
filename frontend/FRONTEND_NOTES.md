# Frontend Notes — Synapse AI Agent

## Component map

| File | Responsibility |
|------|---------------|
| `index.html` | Page shell: sticky header with brand, user nav (`#nav-user`), health dot; `<main id="app">`; footer. Single `<script type="module" src="./js/app.js">`. |
| `styles.css` | Full design system via CSS custom properties. No framework. WCAG AA contrast. Includes all new auth/dashboard/table styles appended at the end. |
| `js/auth.js` | Token storage (`localStorage`), `authHeader()`, `logout()`. No other app imports — bottom of the dependency chain. |
| `js/api.js` | All backend calls. Imports `authHeader / clearToken / getToken` from `auth.js`. `_fetch` injects auth header and dispatches `synapse:unauthorized` on 401. Exports auth, dashboard, and pipeline endpoint functions. |
| `js/state.js` | `createStore(initialState)` — minimal pub/sub store. |
| `js/utils.js` | `esc()`, `formatError()`. |
| `js/markdown.js` | `renderMarkdown()` — used in `reportView` and `reportHistoryView`. |
| `js/loginView.js` | Two-mode form (login / register). Calls `login()` / `register()` from api.js; stores token via `setToken()`; calls `onSuccess()`. |
| `js/dashboardView.js` | Analytics stat cards + paginated run history table. Returns `{ cleanup }`. |
| `js/reportHistoryView.js` | Fetches and renders a single stored report. Returns `{ cleanup }`. |
| `js/queryView.js` | Research query form (unchanged). |
| `js/planView.js` | HITL plan review + inline edit (unchanged). |
| `js/progressView.js` | SSE progress view; returns `{ cleanup }` to stop interval (unchanged). |
| `js/reportView.js` | Report display. Now accepts optional `onBack` and `onNewResearch` callbacks. |
| `js/app.js` | State machine, view dispatcher, boot sequence, nav update, auth event listeners. |

All files are ES modules (`type="module"`). `index.html` loads only `app.js`; all other modules are imported transitively. No bundler, no npm.

---

## State strategy

The store holds a single plain object. `screen` is the routing key.

```
{
  // Auth
  screen:          'login' | 'dashboard' | 'report_history' |
                   'idle' | 'submitting' | 'awaiting_plan_approval' |
                   'resuming' | 'completed' | 'error',
  currentUser:     { id, email, display_name } | null,
  dashboardRunId:  string | null,    // active run for report_history screen

  // Pipeline
  threadId:        string | null,
  query:           string | null,
  plan:            PlanDTO | null,
  interruptPayload: object | null,
  checkpoints:     CheckpointEvent[],
  report:          string | null,
  finalAnswer:     string | null,
  sections:        SectionDTO[] | null,
  sources:         SourceDTO[] | null,
  lowConfidence:   boolean | null,
  error:           unknown,
}
```

`store.subscribe(render)` triggers a full view swap on every `setState`.
View-local state (plan edit mode, pagination page) lives in closure, not the
store, so it only survives within the same mount call.

### Screen transitions

```
boot()
  no token → login
  token    → getMe() → dashboard (or login on 401)

login     → dashboard      (successful login/register)
dashboard → idle           ("New Research")
dashboard → report_history ("View Report" row action)
report_history → dashboard ("Back to Dashboard")

idle → submitting → awaiting_plan_approval → resuming → completed
                                          ↖ (re-interrupt)
completed → dashboard  ("Back to Dashboard", only when authenticated)
completed → idle       ("Start New Research")
any → error            (API failure)
error → idle           ("Start Over")

synapse:logout       → login
synapse:unauthorized → login
```

---

## Boot sequence

```
app.js loads
  → store.subscribe(render)
  → healthCheck() [fire-and-forget, updates header dot]
  → boot()
       ├── getToken() === null  → setState({ screen:'login', currentUser:null })
       └── token exists
             → show spinner (direct DOM write, bypasses store)
             → getMe()
                  ├── ok  → setState({ screen:'dashboard', currentUser:user })
                  └── err → clearToken() → setState({ screen:'login', currentUser:null })
```

`synapse:unauthorized` (dispatched by `_fetch` on any 401) and
`synapse:logout` (dispatched by `logout()`) are both handled by
`window.addEventListener` in app.js, each setting `{ screen:'login', currentUser:null }`.

---

## API contract consumption

| Endpoint | Authenticated | Called by | Key response fields |
|---|---|---|---|
| `POST /auth/register` | No | loginView | `access_token` |
| `POST /auth/login` | No | loginView | `access_token` |
| `GET /auth/me` | Yes | app.js boot + onSuccess | `id, email, display_name` |
| `GET /healthz` | No | app.js | `status, service` |
| `POST /runs` | Yes | app.js submitQuery | `thread_id, status, plan, interrupt_payload` |
| `POST /runs/{id}/resume` | Yes | app.js sendResume | `thread_id, status, report, sections, sources, low_confidence, plan` |
| `GET /runs/{id}/stream` | Via query param | app.js sendResume | SSE: `event, node, step, status, next[]` |
| `GET /dashboard/analytics` | Yes | dashboardView | `total_runs, completed_runs, avg_duration_seconds, avg_sources_per_run` |
| `GET /dashboard/runs` | Yes | dashboardView | `{ runs: [...], total }` |
| `GET /dashboard/runs/{id}/report` | Yes | reportHistoryView | `title, created_at, content, section_count?, source_count?` |

### Auth header injection

`_fetch(url, options, authenticated=true)` spreads `authHeader()` (returns
`{ Authorization: 'Bearer <token>' }` or `{}`) into every authenticated call.
`login()` and `register()` pass `authenticated=false`.

`streamRun` cannot use `Authorization` header (EventSource limitation), so
the token is appended as `?token=<encoded-jwt>`.

### Assumed dashboard response shapes

These are assumed from the task specification; confirm with the backend if they diverge:

- `GET /dashboard/analytics` → `{ total_runs, completed_runs, avg_duration_seconds, avg_sources_per_run }`
- `GET /dashboard/runs` → `{ runs: [{ id, query, status, created_at, duration_seconds, has_report }], total }`
- `GET /dashboard/runs/{id}/report` → `{ title, created_at, content, section_count?, source_count? }`

The dashboard and report-history views use null-safe access (`?.`) and
fallback values (`?? '—'`) throughout, so partial or differently-shaped
responses degrade gracefully.

---

## Cleanup / cancellation

`dashboardView` and `reportHistoryView` maintain an `isActive` boolean.
Each returns `{ cleanup() { isActive = false; } }`. `app.js` stores the
return value in `currentView` and calls `cleanupView()` before every render,
which sets `isActive = false` on the previous instance. Pending `.then()` /
`.catch()` callbacks check `isActive` before touching the DOM.

`progressView` returns `{ cleanup() { clearInterval(cycleTimer); } }` to
stop the stage-label animation interval.

---

## Accessibility notes

- `<nav id="nav-user" aria-label="User navigation">` in the sticky header.
- `aria-live="polite"` on `<main id="app">` and the health status span.
- `role="alert"` + `aria-live="assertive"` on all inline error elements.
- `role="log"` + `aria-live="polite"` on the checkpoint log.
- `role="status"` + `aria-label` on all spinners.
- `scope="col"` on all `<th>` in the run history table.
- `aria-label` on pagination prev/next and "View Report" buttons (includes truncated query for context).
- `aria-disabled="true"` on disabled pagination buttons (in addition to `disabled` attr).
- Login: email field auto-focused; inline errors call `.focus()` for screen readers.
- Dashboard: empty-state message included for zero-run case.
- All interactive elements are keyboard-reachable; focus ring from `:focus-visible`.
- Status badge contrast ratios all exceed WCAG AA: completed (green-900 on green-100 ≈ 8:1), running (blue-700 on blue-100 ≈ 6:1), error (red-800 on red-100 ≈ 6:1), awaiting (amber-900 on amber-100 ≈ 7:1).

---

## Definition-of-done checklist

- [x] Query → plan → approval → progress → report flow navigable and unchanged
- [x] Auth gate: login and register forms with inline error messages
- [x] Mode toggle between login and register forms (no page reload)
- [x] Token stored in `localStorage`; `authHeader()` injected into all authenticated API calls
- [x] Boot sequence validates token via `getMe()`; routes to dashboard or login
- [x] 401 response from any endpoint: clears token, dispatches `synapse:unauthorized`
- [x] `synapse:logout` and `synapse:unauthorized` transition to login screen
- [x] Header nav: user display name + Dashboard + Logout when authenticated; empty when not
- [x] Dashboard analytics: 4 stat cards with loading and error states
- [x] Dashboard run history: paginated table with status badges
- [x] Dashboard: "View Report" button present only when `has_report=true`
- [x] Dashboard: "New Research" button transitions to idle
- [x] Dashboard: Refresh button reloads current page
- [x] Dashboard: empty state message when no runs
- [x] Dashboard: `cleanup()` prevents stale async DOM writes after navigation
- [x] `report_history`: fetches stored report and renders markdown
- [x] `report_history`: shows title, created-at, section count, source count
- [x] `report_history`: loading and error states handled with back button
- [x] `report_history`: `cleanup()` cancels in-flight fetch on navigation
- [x] `completed` screen: "Back to Dashboard" button when authenticated
- [x] `completed` screen: "Start New Research" calls `resetToIdle()` (no page reload)
- [x] Low-confidence warning banner on completed screen preserved
- [x] SSE stream URL includes `?token=` query parameter
- [x] `healthCheck()` called without auth header (public endpoint)
- [x] No secrets or API keys in client code
- [x] Pure ES modules, no bundler, no npm packages
- [x] No external CSS frameworks; only extends existing `styles.css`
- [x] Semantic markup: `header/nav/main/article/section/aside/footer`
- [x] WCAG AA contrast on all new status badges and cards
- [x] All new buttons and links reachable by keyboard (Tab + Enter/Space)
- [x] Responsive: analytics grid 4→2→1 col; table hides secondary cols on mobile
