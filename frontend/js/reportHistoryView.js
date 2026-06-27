/**
 * Report history view — displays a single stored report fetched by run ID.
 *
 * Fetches GET /dashboard/runs/{runId}/report and renders:
 *   - Report title as a heading
 *   - Metadata: created_at, section count, source count
 *   - Full report content via renderMarkdown
 *   - "Back to Dashboard" button → onBack()
 *
 * Loading and error states are both handled before the report renders.
 *
 * Returns { cleanup } so app.js can cancel the in-flight fetch on navigation.
 *
 * @param {HTMLElement} container
 * @param {{ runId: string, onBack: () => void }} props
 * @returns {{ cleanup: () => void }}
 */

import { getStoredReport } from './api.js';
import { renderMarkdown }  from './markdown.js';
import { esc }             from './utils.js';

export function renderReportHistoryView(container, { runId, onBack }) {
  let isActive = true;

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  container.innerHTML = `
    <div class="view view-report-history">
      <div class="report-history-nav">
        <button class="btn btn-secondary btn-sm" id="history-back-loading" type="button">
          &#8592; Back to Dashboard
        </button>
      </div>
      <div class="card center-card">
        <div class="spinner" role="status" aria-label="Loading report"></div>
        <p class="spinner-label">Loading report&hellip;</p>
      </div>
    </div>
  `;

  container.querySelector('#history-back-loading')
    ?.addEventListener('click', onBack);

  // -------------------------------------------------------------------------
  // Fetch and render
  // -------------------------------------------------------------------------

  getStoredReport(runId)
    .then(data => {
      if (!isActive) return;
      renderReport(data);
    })
    .catch(err => {
      if (!isActive) return;
      renderError(err);
    });

  function renderReport(data) {
    const created = data?.created_at
      ? new Date(data.created_at).toLocaleString(undefined, {
          year: 'numeric', month: 'long', day: 'numeric',
          hour: '2-digit', minute: '2-digit',
        })
      : null;

    // Support multiple field names the backend might use
    const content = data?.content ?? data?.report ?? '';

    const sectionCount = data?.section_count
      ?? (Array.isArray(data?.sections) ? data.sections.length : null);
    const sourceCount  = data?.source_count
      ?? (Array.isArray(data?.sources) ? data.sources.length : null);

    const metaBadges = [
      created      ? `<span class="meta-badge">${esc(created)}</span>`                    : '',
      sectionCount != null ? `<span class="meta-badge">${sectionCount} sections</span>`   : '',
      sourceCount  != null ? `<span class="meta-badge">${sourceCount} sources</span>`     : '',
    ].filter(Boolean).join('');

    container.innerHTML = `
      <div class="view view-report-history">
        <div class="report-history-nav">
          <button class="btn btn-secondary btn-sm" id="history-back" type="button">
            &#8592; Back to Dashboard
          </button>
        </div>

        <article class="card report-card" aria-label="Stored research report">
          <header class="card-header report-header">
            <h2>${esc(data?.title || 'Research Report')}</h2>
            ${metaBadges ? `<div class="report-badges" aria-label="Report metadata">${metaBadges}</div>` : ''}
          </header>

          <div class="report-prose" id="report-history-body">
            ${content ? renderMarkdown(content) : '<p class="muted">No content available for this report.</p>'}
          </div>
        </article>
      </div>
    `;

    container.querySelector('#history-back')
      ?.addEventListener('click', onBack);
  }

  function renderError(err) {
    let msg = 'Failed to load the report. It may have been deleted or is no longer available.';
    if (err?.body) {
      const b = err.body;
      msg = (b.detail && !Array.isArray(b.detail)) ? String(b.detail)
          : Array.isArray(b.detail) ? b.detail.map(d => d.msg ?? JSON.stringify(d)).join('; ')
          : b.error ? String(b.error)
          : err.message || msg;
    } else if (err instanceof Error) {
      msg = err.message;
    }

    container.innerHTML = `
      <div class="view view-report-history">
        <div class="report-history-nav">
          <button class="btn btn-secondary btn-sm" id="history-back-err" type="button">
            &#8592; Back to Dashboard
          </button>
        </div>
        <div class="card error-card" style="max-width:520px;margin:2rem auto;">
          <h2>Could not load report</h2>
          <p class="error-message" role="alert">${esc(msg)}</p>
        </div>
      </div>
    `;

    container.querySelector('#history-back-err')
      ?.addEventListener('click', onBack);
  }

  // -------------------------------------------------------------------------
  // Cleanup
  // -------------------------------------------------------------------------

  return {
    cleanup() {
      isActive = false;
    },
  };
}
