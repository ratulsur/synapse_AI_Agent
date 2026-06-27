/**
 * Synapse AI Agent — main application entry point.
 *
 * State machine
 * -------------
 *   login                     (auth gate — shown when no valid token)
 *     -> dashboard            (on successful login / valid session)
 *   dashboard                 (run history + analytics)
 *     -> idle                 (user clicks "New Research")
 *     -> report_history       (user clicks "View Report" on a run row)
 *   report_history            (stored report for a past run)
 *     -> dashboard            ("Back to Dashboard")
 *   idle
 *     -> submitting           (user submits query)
 *   submitting
 *     -> awaiting_plan_approval  (POST /runs returns awaiting_plan_approval)
 *     -> completed               (POST /runs returns completed — unusual path)
 *     -> error
 *   awaiting_plan_approval
 *     -> resuming             (user clicks Approve / Edit / Reject)
 *   resuming
 *     -> awaiting_plan_approval  (POST /resume returns awaiting_plan_approval — re-interrupt)
 *     -> completed               (POST /resume returns completed)
 *     -> error
 *   completed                    (terminal display state)
 *     -> dashboard            ("Back to Dashboard")
 *     -> idle                 ("Start New Research")
 *   error                        (terminal display state; "Start Over" resets to idle)
 *
 * Global events
 * -------------
 *   synapse:logout        → transition to login
 *   synapse:unauthorized  → transition to login (401 from any API call)
 *
 * The SSE stream (GET /runs/{id}/stream) is opened in parallel with the
 * POST /resume call and feeds incremental checkpoint events to the progress
 * view. Because graph.invoke() is synchronous on the server, SSE events may
 * all arrive after the POST returns — the POST response is always authoritative
 * for the final state.
 */

import { createStore }                               from './state.js';
import { healthCheck, startRun, resumeRun, streamRun, getMe } from './api.js';
import { getToken, clearToken, logout }              from './auth.js';
import { mountQueryView }                            from './queryView.js';
import { mountPlanView }                             from './planView.js';
import { mountProgressView, updateProgressView }     from './progressView.js';
import { mountReportView }                           from './reportView.js';
import { renderLoginView }                           from './loginView.js';
import { renderDashboardView }                       from './dashboardView.js';
import { renderReportHistoryView }                   from './reportHistoryView.js';
import { esc, formatError }                          from './utils.js';

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

const store = createStore({
  /**
   * @type {'login'|'dashboard'|'report_history'|
   *        'idle'|'submitting'|'awaiting_plan_approval'|'resuming'|'completed'|'error'}
   */
  screen: 'idle',
  /** @type {{ id?: string, email?: string, display_name?: string }|null} */
  currentUser: null,
  /** @type {string|null} Run ID for the report_history screen. */
  dashboardRunId: null,
  /** @type {string|null} */
  threadId: null,
  /** @type {string|null} */
  query: null,
  /** @type {object|null} Plan object from the backend (PlanDTO shape). */
  plan: null,
  /** @type {object|null} Full interrupt_payload from the backend. */
  interruptPayload: null,
  /** @type {Array} SSE checkpoint events (may be empty if SSE is unavailable). */
  checkpoints: [],
  /** @type {string|null} */
  report: null,
  /** @type {string|null} JSON-serialised terminal payload. */
  finalAnswer: null,
  /** @type {Array|null} */
  sections: null,
  /** @type {Array|null} */
  sources: null,
  /** @type {boolean|null} */
  lowConfidence: null,
  /** @type {unknown} Last error (ApiError, Error, or string). */
  error: null,
});

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const appEl     = document.getElementById('app');
const healthEl  = document.getElementById('health-status');
const healthDot = document.getElementById('health-dot');

// ---------------------------------------------------------------------------
// View lifecycle — cleanup function from the current view
// ---------------------------------------------------------------------------

/** @type {null|{ cleanup: () => void }} */
let currentView = null;

function cleanupView() {
  if (currentView && typeof currentView.cleanup === 'function') {
    currentView.cleanup();
  }
  currentView = null;
}

// ---------------------------------------------------------------------------
// Navigation bar — updated on every render to reflect auth state
// ---------------------------------------------------------------------------

function updateNav(state) {
  const navEl = document.getElementById('nav-user');
  if (!navEl) return;

  if (state.currentUser) {
    const displayName = esc(
      state.currentUser.display_name || state.currentUser.email || 'User'
    );
    const emailLabel = esc(state.currentUser.email || '');
    navEl.innerHTML = `
      <span
        class="nav-user-name"
        id="nav-user-name"
        aria-label="Logged in as ${emailLabel}"
      >${displayName}</span>
      <button
        class="btn btn-sm btn-secondary"
        id="nav-dashboard-btn"
        type="button"
        aria-label="Go to dashboard"
      >Dashboard</button>
      <button
        class="btn btn-sm btn-danger"
        id="nav-logout-btn"
        type="button"
      >Logout</button>
    `;
    navEl.querySelector('#nav-dashboard-btn').addEventListener('click', () => {
      store.setState({ screen: 'dashboard' });
    });
    navEl.querySelector('#nav-logout-btn').addEventListener('click', () => {
      logout();
    });
  } else {
    navEl.innerHTML = '';
  }
}

// ---------------------------------------------------------------------------
// Render dispatcher — called on every state change
// ---------------------------------------------------------------------------

function render(state) {
  updateNav(state);
  cleanupView();
  appEl.innerHTML = '';

  switch (state.screen) {

    // ------------------------- Auth screens --------------------------------

    case 'login':
      renderLoginView(appEl, async () => {
        // loginView has stored the token; fetch user info then go to dashboard
        try {
          const user = await getMe();
          store.setState({ screen: 'dashboard', currentUser: user });
        } catch {
          // Token was stored but getMe failed — proceed to dashboard anyway
          store.setState({ screen: 'dashboard', currentUser: null });
        }
      });
      break;

    case 'dashboard': {
      const result = renderDashboardView(appEl, {
        onNewResearch: resetToIdle,
        onViewReport: (runId) => {
          store.setState({ screen: 'report_history', dashboardRunId: runId });
        },
      });
      currentView = result || null;
      break;
    }

    case 'report_history': {
      const result = renderReportHistoryView(appEl, {
        runId:  state.dashboardRunId,
        onBack: () => store.setState({ screen: 'dashboard' }),
      });
      currentView = result || null;
      break;
    }

    // ----------------------- Research pipeline screens ---------------------

    case 'idle':
      mountQueryView(appEl, { onSubmit: submitQuery });
      break;

    case 'submitting':
      mountSpinner(appEl, 'Generating research plan…');
      break;

    case 'awaiting_plan_approval':
      mountPlanView(appEl, {
        plan:             state.plan || {},
        interruptPayload: state.interruptPayload || {},
        onApprove: ()              => sendResume('approve', null),
        onEdit:    (edited_plan)   => sendResume('edit', edited_plan),
        onReject:  ()              => sendResume('reject', null),
      });
      break;

    case 'resuming': {
      const result = mountProgressView(appEl, { checkpoints: state.checkpoints });
      currentView = result || null;
      break;
    }

    case 'completed':
      mountReportView(appEl, {
        report:        state.report,
        finalAnswer:   state.finalAnswer,
        sections:      state.sections,
        sources:       state.sources,
        lowConfidence: state.lowConfidence,
        plan:          state.plan,
        onBack:        state.currentUser
                         ? () => store.setState({ screen: 'dashboard' })
                         : null,
        onNewResearch: resetToIdle,
      });
      break;

    case 'error':
      mountErrorView(appEl, state.error, resetToIdle);
      break;

    default:
      mountErrorView(appEl, `Unknown screen: ${state.screen}`, resetToIdle);
  }
}

// ---------------------------------------------------------------------------
// Simple utility views (inline — not worth separate files)
// ---------------------------------------------------------------------------

function mountSpinner(container, message) {
  container.innerHTML = `
    <div class="view view-loading">
      <div class="card center-card">
        <div class="spinner" role="status" aria-label="${esc(message)}"></div>
        <p class="spinner-label" aria-live="polite">${esc(message)}</p>
      </div>
    </div>
  `;
}

function mountErrorView(container, err, onRetry) {
  const { message, detail } = formatError(err);
  container.innerHTML = `
    <div class="view view-error">
      <div class="card error-card">
        <h2>Something went wrong</h2>
        <p class="error-message" role="alert">${esc(message)}</p>
        ${detail ? `<p class="error-detail">${esc(detail)}</p>` : ''}
        <div class="form-actions">
          <button class="btn btn-primary" id="retry-btn" type="button">Start Over</button>
        </div>
      </div>
    </div>
  `;
  container.querySelector('#retry-btn').addEventListener('click', onRetry);
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function submitQuery({ query, max_retrieval_iterations, max_revise_iterations }) {
  store.setState({
    screen: 'submitting',
    query,
    error: null,
    checkpoints: [],
    threadId: null,
    plan: null,
    interruptPayload: null,
    report: null,
    finalAnswer: null,
    sections: null,
    sources: null,
    lowConfidence: null,
  });

  try {
    const data = await startRun({ query, max_retrieval_iterations, max_revise_iterations });
    handleRunResponse(data);
  } catch (err) {
    store.setState({ screen: 'error', error: err });
  }
}

/** Handle the response from either POST /runs or POST /runs/{id}/resume. */
function handleRunResponse(data) {
  if (data.status === 'awaiting_plan_approval') {
    store.setState({
      screen: 'awaiting_plan_approval',
      threadId: data.thread_id,
      plan: data.plan,
      interruptPayload: data.interrupt_payload,
    });
  } else if (data.status === 'completed') {
    store.setState({
      screen: 'completed',
      threadId: data.thread_id,
      plan: data.plan,
      report: data.report,
      finalAnswer: data.final_answer,
      sections: data.sections,
      sources: data.sources,
      lowConfidence: data.low_confidence,
    });
  } else if (data.status === 'error') {
    store.setState({
      screen: 'error',
      error: { message: 'The pipeline returned an error status.' },
    });
  } else {
    store.setState({
      screen: 'error',
      error: { message: `Unexpected status from backend: "${data.status}"` },
    });
  }
}

/** @type {{ close: () => void }|null} */
let sseConnection = null;

/**
 * Resume a paused run (approve / edit / reject).
 *
 * Simultaneously:
 *   1. POST /runs/{id}/resume (authoritative, blocking, may take minutes)
 *   2. Open SSE stream for incremental progress events (supplemental)
 *
 * @param {'approve'|'edit'|'reject'} action
 * @param {object|null} edited_plan  Required when action === 'edit'.
 */
async function sendResume(action, edited_plan) {
  const { threadId } = store.getState();
  if (!threadId) {
    store.setState({ screen: 'error', error: { message: 'No active thread to resume.' } });
    return;
  }

  // Transition to progress view
  store.setState({ screen: 'resuming', checkpoints: [] });

  // Open SSE stream in parallel with the POST
  if (sseConnection) { sseConnection.close(); sseConnection = null; }
  sseConnection = streamRun(threadId, {
    onEvent(checkpoint) {
      // Append to checkpoints list (most-recent-first from server, so we prepend)
      store.setState(s => ({ checkpoints: [checkpoint, ...s.checkpoints] }));
      // Also drive incremental DOM updates on the progress view
      if (store.getState().screen === 'resuming') {
        updateProgressView(appEl, checkpoint);
      }
    },
    onDone() {
      sseConnection = null;
    },
    onError() {
      // SSE unavailable during blocking invoke — not fatal.
      // The POST response is authoritative.
      sseConnection = null;
    },
  });

  try {
    const data = await resumeRun(threadId, {
      action,
      edited_plan: edited_plan ?? null,
    });

    // Close SSE — we now have the full authoritative response
    if (sseConnection) { sseConnection.close(); sseConnection = null; }

    handleRunResponse(data);
  } catch (err) {
    if (sseConnection) { sseConnection.close(); sseConnection = null; }
    store.setState({ screen: 'error', error: err });
  }
}

function resetToIdle() {
  if (sseConnection) { sseConnection.close(); sseConnection = null; }
  cleanupView();
  store.setState({
    screen: 'idle',
    threadId: null,
    query: null,
    plan: null,
    interruptPayload: null,
    checkpoints: [],
    report: null,
    finalAnswer: null,
    sections: null,
    sources: null,
    lowConfidence: null,
    error: null,
  });
}

// ---------------------------------------------------------------------------
// Global auth event listeners
// ---------------------------------------------------------------------------

window.addEventListener('synapse:logout', () => {
  store.setState({ screen: 'login', currentUser: null });
});

window.addEventListener('synapse:unauthorized', () => {
  store.setState({ screen: 'login', currentUser: null });
});

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

// Subscribe render to every state change
store.subscribe(render);

// Health check on load — update the header status indicator
healthCheck()
  .then(data => {
    if (healthEl)  healthEl.textContent = `${data.service} — ready`;
    if (healthDot) { healthDot.className = 'health-dot dot-ok'; healthDot.title = 'Backend reachable'; }
  })
  .catch(() => {
    if (healthEl)  healthEl.textContent = 'Backend unavailable';
    if (healthDot) { healthDot.className = 'health-dot dot-error'; healthDot.title = 'Cannot reach backend'; }
  });

// Boot sequence: validate stored token → dashboard, or show login
boot();

async function boot() {
  const token = getToken();

  if (!token) {
    store.setState({ screen: 'login', currentUser: null });
    return;
  }

  // Show a loading screen while we validate the token
  appEl.innerHTML = `
    <div class="view view-loading">
      <div class="card center-card">
        <div class="spinner" role="status" aria-label="Verifying session"></div>
        <p class="spinner-label">Verifying session&hellip;</p>
      </div>
    </div>
  `;

  try {
    const user = await getMe();
    store.setState({ screen: 'dashboard', currentUser: user });
  } catch {
    // Token was invalid or expired — clear it and show login
    clearToken();
    store.setState({ screen: 'login', currentUser: null });
  }
}
