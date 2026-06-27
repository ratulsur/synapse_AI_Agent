/**
 * Dashboard view.
 *
 * Renders:
 *   1. Analytics cards — total runs, completed, avg duration, avg sources.
 *      Fetched from GET /dashboard/analytics.
 *   2. Run history table — query, status badge, created date, duration, action.
 *      Fetched from GET /dashboard/runs with prev/next pagination + refresh.
 *   3. "New Research" button (top-right) → onNewResearch().
 *   4. "View Report" per-row button (when has_report=true) → onViewReport(runId).
 *
 * Returns { cleanup } so app.js can cancel in-flight async work on navigation.
 *
 * @param {HTMLElement} container
 * @param {{ onNewResearch: () => void, onViewReport: (runId: string) => void }} callbacks
 * @returns {{ cleanup: () => void }}
 */

import { getDashboardRuns, getAnalytics } from './api.js';
import { esc }                             from './utils.js';

export function renderDashboardView(container, { onNewResearch, onViewReport }) {
  let isActive = true;
  let currentPage = 1;
  const LIMIT = 20;
  let totalPages = 1;

  // -------------------------------------------------------------------------
  // Initial shell — loading placeholders
  // -------------------------------------------------------------------------

  container.innerHTML = `
    <div class="view view-dashboard">
      <div class="dashboard-header">
        <h2>Dashboard</h2>
        <button class="btn btn-primary" id="dashboard-new-research" type="button">
          New Research
        </button>
      </div>

      <section aria-label="Analytics" id="dashboard-analytics" class="dashboard-analytics">
        <div class="analytics-loading">
          <div class="spinner spinner-sm" role="status" aria-label="Loading analytics"></div>
        </div>
      </section>

      <section aria-label="Run history" class="card" id="dashboard-runs-card">
        <div class="runs-card-header">
          <h3>Run History</h3>
        </div>
        <div class="spinner-block">
          <div class="spinner" role="status" aria-label="Loading runs"></div>
        </div>
      </section>
    </div>
  `;

  container.querySelector('#dashboard-new-research')
    .addEventListener('click', onNewResearch);

  // -------------------------------------------------------------------------
  // Analytics
  // -------------------------------------------------------------------------

  async function loadAnalytics() {
    const el = container.querySelector('#dashboard-analytics');
    try {
      const data = await getAnalytics();
      if (!isActive || !el) return;
      el.innerHTML = renderAnalyticsCards(data);
    } catch {
      if (!isActive || !el) return;
      el.innerHTML = `<p class="muted analytics-error">Analytics unavailable.</p>`;
    }
  }

  function renderAnalyticsCards(data) {
    const cards = [
      { label: 'Total Runs',    value: data?.total_runs      ?? '—' },
      { label: 'Completed',     value: data?.completed_runs  ?? '—' },
      { label: 'Avg Duration',  value: formatDuration(data?.avg_duration_seconds) },
      { label: 'Avg Sources',   value: data?.avg_sources_per_run != null
                                          ? Number(data.avg_sources_per_run).toFixed(1)
                                          : '—' },
    ];
    return cards.map(c => `
      <div class="analytics-card">
        <div class="analytics-value">${esc(String(c.value))}</div>
        <div class="analytics-label">${esc(c.label)}</div>
      </div>
    `).join('');
  }

  // -------------------------------------------------------------------------
  // Run table
  // -------------------------------------------------------------------------

  async function loadRuns(page = 1) {
    const card = container.querySelector('#dashboard-runs-card');
    if (!card) return;

    card.innerHTML = `
      <div class="runs-card-header">
        <h3>Run History</h3>
      </div>
      <div class="spinner-block">
        <div class="spinner" role="status" aria-label="Loading runs"></div>
      </div>
    `;

    try {
      const data = await getDashboardRuns({ page, limit: LIMIT });
      if (!isActive) return;
      const card2 = container.querySelector('#dashboard-runs-card');
      if (!card2) return;

      const runs = Array.isArray(data?.runs) ? data.runs : [];
      const total = typeof data?.total === 'number' ? data.total : runs.length;
      totalPages = Math.max(1, Math.ceil(total / LIMIT));
      currentPage = page;

      card2.innerHTML = renderRunsTable(runs, currentPage, totalPages);
      wireRunsTable(card2);
    } catch {
      if (!isActive) return;
      const card2 = container.querySelector('#dashboard-runs-card');
      if (!card2) return;
      card2.innerHTML = `
        <div class="runs-card-header"><h3>Run History</h3></div>
        <p class="muted" style="padding: var(--space-4);">Failed to load run history.</p>
      `;
    }
  }

  function renderRunsTable(runs, page, total) {
    const header = `
      <div class="runs-card-header">
        <h3>Run History</h3>
        <button class="btn btn-sm btn-secondary" id="runs-refresh" type="button">Refresh</button>
      </div>
    `;

    if (runs.length === 0) {
      return header + `
        <p class="muted dashboard-empty">
          No research runs yet. Click <strong>New Research</strong> to get started.
        </p>
      `;
    }

    const rows = runs.map(run => {
      const rawQuery = run.query || '';
      const queryDisplay = rawQuery.length > 60
        ? esc(rawQuery.slice(0, 60)) + '&hellip;'
        : esc(rawQuery || '—');

      const created = run.created_at
        ? new Date(run.created_at).toLocaleString(undefined, {
            year: 'numeric', month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit',
          })
        : '—';

      const duration = formatDuration(run.duration_seconds);
      const action   = run.has_report
        ? `<button
             class="btn btn-xs btn-secondary"
             data-view-report="${esc(run.id)}"
             type="button"
             aria-label="View report for: ${esc(rawQuery.slice(0, 60))}"
           >View Report</button>`
        : '<span class="muted" aria-label="No report available">—</span>';

      return `
        <tr>
          <td class="run-query-cell" title="${esc(rawQuery)}">${queryDisplay}</td>
          <td>${statusBadge(run.status)}</td>
          <td class="run-date-cell">${esc(created)}</td>
          <td>${esc(duration)}</td>
          <td>${action}</td>
        </tr>
      `;
    }).join('');

    const pagination = `
      <div class="pagination" role="navigation" aria-label="Run history pagination">
        <button
          class="btn btn-sm btn-secondary"
          id="page-prev"
          type="button"
          ${page <= 1 ? 'disabled aria-disabled="true"' : ''}
          aria-label="Previous page"
        >Previous</button>
        <span class="pagination-info" aria-live="polite">Page ${page} of ${total}</span>
        <button
          class="btn btn-sm btn-secondary"
          id="page-next"
          type="button"
          ${page >= total ? 'disabled aria-disabled="true"' : ''}
          aria-label="Next page"
        >Next</button>
      </div>
    `;

    return header + `
      <div class="run-table-wrapper">
        <table class="run-table" aria-label="Research run history">
          <thead>
            <tr>
              <th scope="col">Query</th>
              <th scope="col">Status</th>
              <th scope="col">Created</th>
              <th scope="col">Duration</th>
              <th scope="col">Action</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${pagination}
    `;
  }

  function wireRunsTable(card) {
    card.querySelectorAll('[data-view-report]').forEach(btn => {
      btn.addEventListener('click', () => onViewReport(btn.dataset.viewReport));
    });

    card.querySelector('#page-prev')?.addEventListener('click', () => loadRuns(currentPage - 1));
    card.querySelector('#page-next')?.addEventListener('click', () => loadRuns(currentPage + 1));
    card.querySelector('#runs-refresh')?.addEventListener('click', () => loadRuns(currentPage));
  }

  // -------------------------------------------------------------------------
  // Kick off data loading
  // -------------------------------------------------------------------------

  loadAnalytics();
  loadRuns(1);

  // -------------------------------------------------------------------------
  // Cleanup — cancels pending DOM updates if the user navigates away
  // -------------------------------------------------------------------------

  return {
    cleanup() {
      isActive = false;
    },
  };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format a duration in seconds into a human-readable string.
 * @param {number|null|undefined} seconds
 * @returns {string}
 */
function formatDuration(seconds) {
  if (seconds == null || typeof seconds !== 'number' || isNaN(seconds)) return '—';
  const s = Math.round(Math.abs(seconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m === 0) return `${rem}s`;
  return `${m}m ${rem}s`;
}

/**
 * Render a colored status badge for a run status string.
 * @param {string|null|undefined} status
 * @returns {string}  HTML string
 */
function statusBadge(status) {
  const map = {
    completed:              'badge-completed',
    running:                'badge-running',
    resuming:               'badge-running',
    submitting:             'badge-running',
    error:                  'badge-error',
    awaiting_plan_approval: 'badge-awaiting',
    awaiting:               'badge-awaiting',
  };
  const cls = map[status] ?? 'badge-unknown';
  return `<span class="status-badge ${cls}">${esc(status || 'unknown')}</span>`;
}
