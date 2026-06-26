/**
 * Plan review / HITL view.
 *
 * Renders the generated ReportPlan (audience / length / tone / sections)
 * and provides three actions:
 *   Approve  -> onApprove()                            -> POST /resume { action:"approve" }
 *   Edit     -> in-view editor -> onEdit(edited_plan)  -> POST /resume { action:"edit", edited_plan }
 *   Reject   -> onReject()                             -> POST /resume { action:"reject" }
 *
 * After edit/reject the backend re-runs scope_plan and returns another
 * awaiting_plan_approval response; the app re-mounts this view with the
 * updated plan.  This view is stateless with respect to that outer loop.
 *
 * edited_plan shape (PlanDTO):
 *   { audience, length, tone, sections: [{id, heading, intent, order}] }
 *
 * @param {HTMLElement} container
 * @param {{
 *   plan: { audience?: string, length?: string, tone?: string, sections?: Array },
 *   interruptPayload?: { event?: string, query?: string, plan?: object, instructions?: string },
 *   onApprove: () => void,
 *   onEdit: (edited_plan: object) => void,
 *   onReject: () => void,
 * }} props
 */

import { esc } from './utils.js';

export function mountPlanView(container, { plan, interruptPayload, onApprove, onEdit, onReject }) {
  // Internal mode: 'review' | 'edit'
  let mode = 'review';

  // Mutable edit state (initialised from plan when entering edit mode)
  let editState = null;

  // -------------------------------------------------------------------------
  // Review mode
  // -------------------------------------------------------------------------

  function renderReview() {
    const sections = sortedSections(plan.sections);
    const query = interruptPayload?.query || '';
    const instructions = interruptPayload?.instructions || '';

    return `
      <div class="view view-plan">
        <div class="card">
          <header class="card-header">
            <h2>Review Research Plan</h2>
            <p class="lead">
              The agent has generated a research plan. Approve it to proceed,
              edit individual fields, or reject to have the agent regenerate from scratch.
            </p>
            ${query ? `<p class="query-echo"><strong>Query:</strong> ${esc(query)}</p>` : ''}
          </header>

          <section class="plan-meta" aria-label="Plan parameters">
            <div class="plan-meta-grid">
              <div class="meta-item">
                <span class="meta-label">Audience</span>
                <span class="meta-value">${esc(plan.audience || 'general')}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">Length</span>
                <span class="meta-value">${esc(plan.length || 'medium')}</span>
              </div>
              <div class="meta-item">
                <span class="meta-label">Tone</span>
                <span class="meta-value">${esc(plan.tone || 'neutral')}</span>
              </div>
            </div>
          </section>

          <section class="plan-sections-block" aria-label="Planned sections">
            <h3>Sections <span class="badge">${sections.length}</span></h3>
            <ol class="section-list">
              ${sections.map(s => `
                <li class="section-list-item">
                  <div class="section-list-heading">${esc(s.heading)}</div>
                  ${s.intent ? `<div class="section-list-intent">${esc(s.intent)}</div>` : ''}
                </li>
              `).join('')}
            </ol>
          </section>

          ${instructions ? `
            <section class="plan-instructions" aria-label="Agent instructions">
              <h4>Agent instructions</h4>
              <p>${esc(instructions)}</p>
            </section>
          ` : ''}

          <div class="plan-actions" role="group" aria-label="Plan decisions">
            <button class="btn btn-primary" id="approve-btn" type="button">
              Approve Plan
            </button>
            <button class="btn btn-secondary" id="edit-btn" type="button">
              Edit Plan
            </button>
            <button class="btn btn-danger" id="reject-btn" type="button">
              Reject &amp; Regenerate
            </button>
          </div>
        </div>
      </div>
    `;
  }

  // -------------------------------------------------------------------------
  // Edit mode
  // -------------------------------------------------------------------------

  function buildEditState() {
    const sections = sortedSections(plan.sections).map(s => ({ ...s }));
    return {
      audience: plan.audience || 'general',
      length: plan.length || 'medium',
      tone: plan.tone || 'neutral',
      sections,
    };
  }

  function renderSectionEditor(sec, idx, total) {
    return `
      <div class="section-editor" data-index="${idx}">
        <div class="section-editor-header">
          <span class="section-num" aria-hidden="true">${idx + 1}</span>
          <div class="section-editor-controls">
            ${idx > 0 ? `<button type="button" class="btn btn-xs" data-move-up="${idx}" aria-label="Move section ${idx + 1} up">↑</button>` : '<span class="btn-placeholder"></span>'}
            ${idx < total - 1 ? `<button type="button" class="btn btn-xs" data-move-down="${idx}" aria-label="Move section ${idx + 1} down">↓</button>` : '<span class="btn-placeholder"></span>'}
            <button type="button" class="btn btn-xs btn-danger" data-remove="${idx}" aria-label="Remove section ${idx + 1}: ${esc(sec.heading || 'Untitled')}">×</button>
          </div>
        </div>
        <div class="field">
          <label for="sec-heading-${idx}">Heading</label>
          <input
            type="text"
            id="sec-heading-${idx}"
            class="sec-heading-input"
            data-field="heading"
            data-index="${idx}"
            value="${esc(sec.heading)}"
            placeholder="Section heading"
            required
          >
        </div>
        <div class="field">
          <label for="sec-intent-${idx}">Intent</label>
          <textarea
            id="sec-intent-${idx}"
            class="sec-intent-input"
            data-field="intent"
            data-index="${idx}"
            rows="2"
            placeholder="What this section should cover"
          >${esc(sec.intent || '')}</textarea>
        </div>
      </div>
    `;
  }

  function renderEdit() {
    if (!editState) editState = buildEditState();
    const { audience, length, tone, sections } = editState;

    return `
      <div class="view view-plan">
        <div class="card">
          <header class="card-header">
            <h2>Edit Research Plan</h2>
            <p class="lead">
              Modify the plan and submit. The agent will re-scope based on your edits
              and present an updated plan for review.
            </p>
          </header>

          <form id="edit-form" novalidate>
            <section class="edit-meta" aria-label="Plan parameters">
              <div class="field">
                <label for="edit-audience">Audience</label>
                <input
                  type="text"
                  id="edit-audience"
                  value="${esc(audience)}"
                  placeholder="e.g. general, technical, executives"
                >
              </div>
              <div class="edit-meta-row">
                <div class="field">
                  <label for="edit-length">Length</label>
                  <select id="edit-length">
                    <option value="short"  ${length === 'short'  ? 'selected' : ''}>Short</option>
                    <option value="medium" ${length === 'medium' ? 'selected' : ''}>Medium</option>
                    <option value="long"   ${length === 'long'   ? 'selected' : ''}>Long</option>
                  </select>
                </div>
                <div class="field">
                  <label for="edit-tone">Tone</label>
                  <select id="edit-tone">
                    <option value="neutral"          ${tone === 'neutral'          ? 'selected' : ''}>Neutral</option>
                    <option value="formal"           ${tone === 'formal'           ? 'selected' : ''}>Formal</option>
                    <option value="conversational"   ${tone === 'conversational'   ? 'selected' : ''}>Conversational</option>
                  </select>
                </div>
              </div>
            </section>

            <section class="edit-sections" aria-label="Edit sections">
              <div class="edit-sections-header">
                <h3>Sections</h3>
                <button type="button" class="btn btn-sm btn-secondary" id="add-section-btn">
                  + Add Section
                </button>
              </div>
              <div id="sections-list">
                ${sections.map((s, i) => renderSectionEditor(s, i, sections.length)).join('')}
              </div>
            </section>

            <div id="edit-error" class="error-inline" hidden role="alert" aria-live="assertive"></div>

            <div class="plan-actions" role="group" aria-label="Edit actions">
              <button type="button" class="btn btn-primary" id="save-edit-btn">
                Submit Edits
              </button>
              <button type="button" class="btn btn-secondary" id="cancel-edit-btn">
                Cancel
              </button>
            </div>
          </form>
        </div>
      </div>
    `;
  }

  // -------------------------------------------------------------------------
  // Event wiring
  // -------------------------------------------------------------------------

  function wireReview() {
    container.querySelector('#approve-btn').addEventListener('click', onApprove);

    container.querySelector('#edit-btn').addEventListener('click', () => {
      mode = 'edit';
      editState = buildEditState();
      render();
    });

    container.querySelector('#reject-btn').addEventListener('click', () => {
      if (window.confirm('Reject this plan and ask the agent to generate a new one from scratch?')) {
        onReject();
      }
    });
  }

  function wireEdit() {
    // Save current DOM values back into editState
    function snapshotDOM() {
      editState.audience = container.querySelector('#edit-audience').value;
      editState.length   = container.querySelector('#edit-length').value;
      editState.tone     = container.querySelector('#edit-tone').value;

      container.querySelectorAll('.sec-heading-input').forEach(el => {
        const i = parseInt(el.dataset.index, 10);
        if (editState.sections[i] !== undefined) {
          editState.sections[i].heading = el.value;
        }
      });
      container.querySelectorAll('.sec-intent-input').forEach(el => {
        const i = parseInt(el.dataset.index, 10);
        if (editState.sections[i] !== undefined) {
          editState.sections[i].intent = el.value;
        }
      });
    }

    function showError(msg) {
      const el = container.querySelector('#edit-error');
      if (el) { el.textContent = msg; el.hidden = false; el.focus(); }
    }

    // Add section
    container.querySelector('#add-section-btn').addEventListener('click', () => {
      snapshotDOM();
      editState.sections.push({
        id: `section_${editState.sections.length}`,
        heading: '',
        intent: '',
        order: editState.sections.length,
      });
      render();
      // Focus the new section's heading input
      const inputs = container.querySelectorAll('.sec-heading-input');
      if (inputs.length) inputs[inputs.length - 1].focus();
    });

    // Move up
    container.querySelectorAll('[data-move-up]').forEach(btn => {
      btn.addEventListener('click', () => {
        snapshotDOM();
        const i = parseInt(btn.dataset.moveUp, 10);
        [editState.sections[i - 1], editState.sections[i]] =
          [editState.sections[i], editState.sections[i - 1]];
        render();
        // Re-focus the same logical section (now at i-1)
        const btns = container.querySelectorAll('[data-move-up]');
        if (i - 1 > 0 && btns[i - 1]) btns[i - 1].focus();
      });
    });

    // Move down
    container.querySelectorAll('[data-move-down]').forEach(btn => {
      btn.addEventListener('click', () => {
        snapshotDOM();
        const i = parseInt(btn.dataset.moveDown, 10);
        [editState.sections[i], editState.sections[i + 1]] =
          [editState.sections[i + 1], editState.sections[i]];
        render();
      });
    });

    // Remove
    container.querySelectorAll('[data-remove]').forEach(btn => {
      btn.addEventListener('click', () => {
        if (editState.sections.length <= 1) {
          showError('A plan must have at least one section.');
          return;
        }
        snapshotDOM();
        const i = parseInt(btn.dataset.remove, 10);
        editState.sections.splice(i, 1);
        render();
      });
    });

    // Submit edits
    container.querySelector('#save-edit-btn').addEventListener('click', () => {
      snapshotDOM();

      // Validation
      if (!editState.audience.trim()) {
        showError('Audience is required.');
        container.querySelector('#edit-audience').focus();
        return;
      }
      if (editState.sections.length === 0) {
        showError('At least one section is required.');
        return;
      }
      if (editState.sections.some(s => !s.heading.trim())) {
        showError('All sections must have a heading.');
        return;
      }

      // Build edited_plan matching PlanDTO shape exactly
      const edited_plan = {
        audience: editState.audience.trim(),
        length: editState.length,
        tone: editState.tone,
        sections: editState.sections.map((s, i) => ({
          id: s.id || `section_${i}`,
          heading: s.heading.trim(),
          intent: (s.intent || '').trim(),
          order: i,
        })),
      };

      onEdit(edited_plan);
    });

    // Cancel
    container.querySelector('#cancel-edit-btn').addEventListener('click', () => {
      mode = 'review';
      editState = null;
      render();
    });
  }

  // -------------------------------------------------------------------------
  // Render + wire
  // -------------------------------------------------------------------------

  function render() {
    container.innerHTML = mode === 'review' ? renderReview() : renderEdit();
    if (mode === 'review') wireReview();
    else wireEdit();
  }

  render();
}

// -------------------------------------------------------------------------
// Helper
// -------------------------------------------------------------------------

/** Sort sections by their `order` field ascending. */
function sortedSections(sections) {
  if (!Array.isArray(sections)) return [];
  return [...sections].sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
}
