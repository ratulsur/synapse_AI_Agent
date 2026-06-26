/**
 * Query entry view — the first screen.
 *
 * Renders a research-question textarea plus optional advanced controls
 * (max_retrieval_iterations, max_revise_iterations) that map exactly to
 * the RunRequest DTO in POST /runs.
 *
 * @param {HTMLElement} container
 * @param {{ onSubmit: (params: {
 *   query: string,
 *   max_retrieval_iterations: number|null,
 *   max_revise_iterations: number|null
 * }) => void }} callbacks
 */
export function mountQueryView(container, { onSubmit }) {
  container.innerHTML = `
    <div class="view view-query">
      <div class="card">
        <header class="card-header">
          <h2>Research Query</h2>
          <p class="lead">
            Enter a research question or topic. The agent will scope a plan, retrieve
            grounded evidence across multiple domains, draft report sections, and
            assemble a final report.
          </p>
        </header>

        <form id="query-form" novalidate>
          <div class="field">
            <label for="query-input">Research question <span class="required" aria-hidden="true">*</span></label>
            <textarea
              id="query-input"
              name="query"
              rows="4"
              placeholder="e.g. What are the latest advances in quantum computing hardware?"
              required
              aria-required="true"
              aria-describedby="query-hint query-error"
              autocomplete="off"
              spellcheck="true"
            ></textarea>
            <span id="query-hint" class="field-hint">
              Be specific for best results. The agent searches web, Wikipedia, arXiv and
              other domain-appropriate sources.
            </span>
          </div>

          <details class="advanced-panel">
            <summary class="advanced-toggle">Advanced options</summary>
            <div class="advanced-grid">
              <div class="field">
                <label for="max-retrieval">Max retrieval iterations</label>
                <input
                  type="number"
                  id="max-retrieval"
                  name="max_retrieval_iterations"
                  min="1"
                  max="10"
                  placeholder="Default (3)"
                  aria-describedby="max-retrieval-hint"
                >
                <span id="max-retrieval-hint" class="field-hint">
                  How many times the retriever loops to gather and grade evidence.
                </span>
              </div>
              <div class="field">
                <label for="max-revise">Max revise iterations</label>
                <input
                  type="number"
                  id="max-revise"
                  name="max_revise_iterations"
                  min="1"
                  max="10"
                  placeholder="Default (2)"
                  aria-describedby="max-revise-hint"
                >
                <span id="max-revise-hint" class="field-hint">
                  How many times ungrounded sections are rewritten.
                </span>
              </div>
            </div>
          </details>

          <div id="query-error" class="error-inline" hidden role="alert" aria-live="assertive"></div>

          <div class="form-actions">
            <button type="submit" class="btn btn-primary" id="submit-btn">
              Start Research
            </button>
          </div>
        </form>
      </div>
    </div>
  `;

  const form     = container.querySelector('#query-form');
  const queryEl  = container.querySelector('#query-input');
  const errorEl  = container.querySelector('#query-error');

  form.addEventListener('submit', (e) => {
    e.preventDefault();

    const query = queryEl.value.trim();
    if (!query) {
      errorEl.textContent = 'Please enter a research question before submitting.';
      errorEl.hidden = false;
      queryEl.setAttribute('aria-invalid', 'true');
      queryEl.focus();
      return;
    }
    errorEl.hidden = true;
    queryEl.removeAttribute('aria-invalid');

    const rawRetrieval = container.querySelector('#max-retrieval').value;
    const rawRevise    = container.querySelector('#max-revise').value;

    onSubmit({
      query,
      max_retrieval_iterations: rawRetrieval ? parseInt(rawRetrieval, 10) : null,
      max_revise_iterations:    rawRevise    ? parseInt(rawRevise,    10) : null,
    });
  });

  // Inline error dismissal on first keystroke
  queryEl.addEventListener('input', () => {
    if (!errorEl.hidden) {
      errorEl.hidden = true;
      queryEl.removeAttribute('aria-invalid');
    }
  });

  queryEl.focus();
}
