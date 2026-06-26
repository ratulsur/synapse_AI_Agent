/**
 * Progress view — displayed while POST /runs/{thread_id}/resume is in flight.
 *
 * The view shows:
 *   1. A CSS spinner + animated label.
 *   2. The pipeline stage list, with SSE checkpoint events driving which
 *      stages are highlighted as done / active.
 *   3. An incrementally-updated checkpoint log (if SSE events arrive).
 *
 * Because graph.invoke() is synchronous on the server, SSE events may not
 * arrive until after the POST returns.  The animated label auto-cycles
 * through stage descriptions so the view feels live regardless.
 *
 * @param {HTMLElement} container
 * @param {{ checkpoints: CheckpointEvent[] }} props
 *   checkpoints — SSE events already received (may be empty on first render).
 * @returns {{ cleanup: () => void }}
 */

import { esc } from './utils.js';

/** Ordered pipeline stages (post-approval). */
const STAGES = [
  { node: 'query_router',        label: 'Routing query across domains' },
  { node: 'retrieval_evidence',  label: 'Retrieving and grading evidence' },
  { node: 'write',               label: 'Preparing section writing tasks' },
  { node: 'section_drafting',    label: 'Drafting report sections in parallel' },
  { node: 'grounding_grader',    label: 'Grounding claims against sources' },
  { node: 'revise_section',      label: 'Revising ungrounded sections' },
  { node: 'assemble_report',     label: 'Assembling the final report' },
  { node: 'final_answer',        label: 'Packaging final answer' },
];

/** Human-readable label for a node name (falls back to the raw name). */
function nodeLabel(node) {
  const stage = STAGES.find(s => s.node === node);
  return stage ? stage.label : (node || '—');
}

export function mountProgressView(container, { checkpoints }) {
  // Checkpoints arrive most-recent-first from the server; reverse for display.
  const chronological = [...checkpoints].reverse();
  const completedNodes = new Set(chronological.map(e => e.node).filter(Boolean));
  const lastNode = chronological.length > 0
    ? chronological[chronological.length - 1].node
    : null;

  container.innerHTML = `
    <div class="view view-progress">
      <div class="card progress-card">
        <header class="card-header">
          <h2>Pipeline Running</h2>
          <p class="lead" id="progress-lead">
            The research pipeline is running. This may take several minutes depending
            on query complexity and the number of retrieval iterations.
          </p>
        </header>

        <div class="spinner-block" aria-live="polite" aria-atomic="true">
          <div class="spinner" role="status" aria-label="Pipeline running"></div>
          <p class="spinner-label" id="progress-stage-label">
            ${lastNode ? esc(nodeLabel(lastNode)) : 'Initialising pipeline…'}
          </p>
        </div>

        <section class="pipeline-stages" aria-label="Pipeline stages">
          <h3>Stages</h3>
          <ol class="stage-list" id="stage-list">
            ${STAGES.map(s => {
              const done   = completedNodes.has(s.node);
              const active = s.node === lastNode && !done;
              return `
                <li
                  class="stage-item${done ? ' stage-done' : ''}${active ? ' stage-active' : ''}"
                  data-node="${esc(s.node)}"
                >
                  <span class="stage-icon" aria-hidden="true">${done ? '✓' : active ? '●' : '○'}</span>
                  <span class="stage-label">${esc(s.label)}</span>
                </li>
              `;
            }).join('')}
          </ol>
        </section>

        ${chronological.length > 0 ? `
          <section class="checkpoint-log" aria-label="Checkpoint history">
            <h3>Checkpoint log <span class="badge" id="checkpoint-count">${chronological.length}</span></h3>
            <div class="log-scroll" role="log" aria-live="polite" aria-label="Pipeline checkpoint events">
              <div id="log-entries">
                ${chronological.map(e => renderLogEntry(e)).join('')}
              </div>
            </div>
          </section>
        ` : `
          <section class="checkpoint-log no-events" aria-label="Checkpoint history">
            <h3>Checkpoint log</h3>
            <p class="muted" id="no-events-hint">
              Live checkpoint events will appear here if the server supports concurrent
              streaming (single-worker blocking servers emit all events after completion).
            </p>
            <div role="log" aria-live="polite" aria-label="Pipeline checkpoint events">
              <div id="log-entries"></div>
            </div>
          </section>
        `}
      </div>
    </div>
  `;

  // -------------------------------------------------------------------------
  // Auto-cycling label animation (runs even when SSE events don't arrive)
  // -------------------------------------------------------------------------
  let cycleIdx = 0;
  const labelEl = container.querySelector('#progress-stage-label');
  const stageItems = container.querySelectorAll('.stage-item');

  const cycleTimer = setInterval(() => {
    // Only animate if we have no SSE-driven node info
    if (completedNodes.size === 0) {
      stageItems.forEach((el, i) => {
        el.classList.toggle('stage-active-anim', i === cycleIdx);
      });
      if (labelEl) labelEl.textContent = STAGES[cycleIdx].label + '…';
      cycleIdx = (cycleIdx + 1) % STAGES.length;
    }
  }, 2800);

  return {
    cleanup() {
      clearInterval(cycleTimer);
    },
  };
}

/**
 * Called by app.js when a new SSE checkpoint event arrives while the
 * progress view is mounted. Incrementally updates the DOM without a full
 * re-render.
 *
 * @param {HTMLElement} container
 * @param {CheckpointEvent} checkpoint
 */
export function updateProgressView(container, checkpoint) {
  if (!checkpoint) return;

  // Update spinner label
  const labelEl = container.querySelector('#progress-stage-label');
  if (labelEl && checkpoint.node) {
    labelEl.textContent = nodeLabel(checkpoint.node);
  }

  // Mark the corresponding stage as done
  if (checkpoint.node) {
    const stageEl = container.querySelector(`[data-node="${CSS.escape(checkpoint.node)}"]`);
    if (stageEl) {
      stageEl.classList.remove('stage-active', 'stage-active-anim');
      stageEl.classList.add('stage-done');
      const icon = stageEl.querySelector('.stage-icon');
      if (icon) icon.textContent = '✓';
    }
  }

  // Append to log
  const logEl = container.querySelector('#log-entries');
  if (logEl && checkpoint.event === 'checkpoint') {
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = renderLogEntry(checkpoint);
    logEl.appendChild(entry);
    entry.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // Update count badge
  const countEl = container.querySelector('#checkpoint-count');
  if (countEl) {
    const current = parseInt(countEl.textContent, 10) || 0;
    countEl.textContent = String(current + 1);
  }

  // Hide the "no events" hint once events arrive
  const hintEl = container.querySelector('#no-events-hint');
  if (hintEl) hintEl.hidden = true;
}

// -------------------------------------------------------------------------
// Helpers
// -------------------------------------------------------------------------

function renderLogEntry(e) {
  const statusClass = e.status === 'completed' ? 'status-ok'
    : e.status === 'awaiting_plan_approval' ? 'status-warn' : '';
  return `
    <div class="log-entry">
      <span class="log-step">Step ${e.step ?? '?'}</span>
      <span class="log-node">${esc(nodeLabel(e.node))}</span>
      <span class="log-status ${statusClass}">${esc(e.status || '')}</span>
      ${e.next && e.next.length > 0
        ? `<span class="log-next">→ ${e.next.map(n => esc(nodeLabel(n))).join(', ')}</span>`
        : ''}
    </div>
  `;
}
