/**
 * Report view — rendered when status === "completed".
 *
 * Renders in priority order:
 *   1. Low-confidence banner (if low_confidence === true).
 *   2. Structured section-by-section report (if sections[] is present).
 *   3. Assembled report prose fallback (if only report string is present).
 *   4. Empty state message.
 *
 * Sources panel shows all retrieved evidence sources with title, URL, domain,
 * author, tool, relevance score, and a snippet.  Per-section citations link
 * to their corresponding source cards via smooth-scroll.
 *
 * @param {HTMLElement} container
 * @param {{
 *   report?: string,
 *   finalAnswer?: string,
 *   sections?: SectionDTO[],
 *   sources?: SourceDTO[],
 *   lowConfidence?: boolean,
 *   plan?: { audience?, length?, tone?, sections? },
 * }} props
 */

import { esc } from './utils.js';
import { renderMarkdown } from './markdown.js';

export function mountReportView(container, {
  report,
  sections,
  sources,
  lowConfidence,
  plan,
  onBack,
  onNewResearch,
}) {
  // Build source lookup for citation rendering
  /** @type {Record<string, SourceDTO>} */
  const sourceById = {};
  (sources || []).forEach(s => { sourceById[s.id] = s; });

  // Sort sections to match plan order when possible
  const orderedSections = sortSections(sections, plan);

  container.innerHTML = `
    <div class="view view-report">

      ${lowConfidence ? `
        <div class="banner banner-warning" role="alert" aria-live="assertive">
          <span class="banner-icon" aria-hidden="true">&#9888;</span>
          <div class="banner-body">
            <strong>Low confidence result</strong> &mdash; The source retrieval loop
            reached its iteration cap without fully passing the grading threshold.
            The report is presented with the best available evidence, but some claims
            may have limited source support. Consider refining your query or increasing
            the retrieval iteration limit.
          </div>
        </div>
      ` : ''}

      <article class="card report-card" aria-label="Research report">
        <header class="card-header report-header">
          <h2>Research Report</h2>
          ${plan ? `
            <div class="report-badges" aria-label="Report parameters">
              ${plan.audience ? `<span class="meta-badge">${esc(plan.audience)}</span>` : ''}
              ${plan.tone     ? `<span class="meta-badge">${esc(plan.tone)}</span>`     : ''}
              ${plan.length   ? `<span class="meta-badge">${esc(plan.length)}</span>`   : ''}
            </div>
          ` : ''}
        </header>

        <div class="report-body" id="report-body">
          ${renderBody(orderedSections, report, sourceById)}
        </div>
      </article>

      ${sources && sources.length > 0 ? renderSourcesPanel(sources) : ''}

      <div class="report-footer">
        ${onBack ? `
          <button class="btn btn-secondary" id="back-dashboard-btn" type="button">
            &#8592; Back to Dashboard
          </button>
        ` : ''}
        <button class="btn btn-secondary" id="new-research-btn" type="button">
          Start New Research
        </button>
      </div>

    </div>
  `;

  // -------------------------------------------------------------------------
  // Event wiring
  // -------------------------------------------------------------------------

  // "Back to Dashboard" — only present when onBack is provided
  if (onBack) {
    container.querySelector('#back-dashboard-btn')?.addEventListener('click', onBack);
  }

  // "Start New Research" — calls onNewResearch callback when provided, otherwise reloads
  container.querySelector('#new-research-btn').addEventListener('click', () => {
    if (onNewResearch) {
      onNewResearch();
    } else {
      window.location.reload();
    }
  });

  // Citation links → smooth-scroll to the corresponding source card
  container.querySelectorAll('[data-cite-source]').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const id = link.dataset.citeSource;
      const card = container.querySelector(`[data-source-card="${CSS.escape(id)}"]`);
      if (card) {
        card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        card.classList.add('source-highlight');
        setTimeout(() => card.classList.remove('source-highlight'), 2200);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Body rendering
// ---------------------------------------------------------------------------

function renderBody(sections, report, sourceById) {
  if (sections && sections.length > 0) {
    return sections.map(sec => renderSection(sec, sourceById)).join('\n');
  }
  if (report) {
    return `<div class="report-prose">${renderMarkdown(report)}</div>`;
  }
  return `<p class="muted">No report content is available yet.</p>`;
}

function renderSection(section, sourceById) {
  // Cited sources for this section
  const cites = (section.cited_source_ids || [])
    .map(id => sourceById[id])
    .filter(Boolean);

  const groundedBadge = section.grounded
    ? `<span class="grounded-badge" title="Claims in this section are grounded against sources">Grounded</span>`
    : `<span class="ungrounded-badge" title="This section did not pass grounding verification">Ungrounded</span>`;

  const reviseBadge = section.revise_count > 0
    ? `<span class="revise-badge" title="This section was revised ${section.revise_count} time(s)">Revised &times;${section.revise_count}</span>`
    : '';

  return `
    <section class="report-section" aria-labelledby="sec-h-${esc(section.spec_id)}">
      <div class="section-heading-bar">
        <h3 id="sec-h-${esc(section.spec_id)}">${esc(section.heading)}</h3>
        <div class="section-badges">
          ${groundedBadge}
          ${reviseBadge}
        </div>
      </div>
      <div class="section-content">${renderMarkdown(section.content)}</div>
      ${cites.length > 0 ? `
        <div class="section-citations" aria-label="Citations for this section">
          <span class="citations-label">Sources:</span>
          ${cites.map((src, i) => `
            <a
              href="#src-${esc(src.id)}"
              class="citation-link"
              data-cite-source="${esc(src.id)}"
              title="${esc(src.title)}"
              aria-label="Citation ${i + 1}: ${esc(src.title)}"
            >[${i + 1}]</a>
          `).join('')}
        </div>
      ` : ''}
    </section>
  `;
}

// ---------------------------------------------------------------------------
// Sources panel
// ---------------------------------------------------------------------------

function renderSourcesPanel(sources) {
  return `
    <aside class="card sources-card" aria-label="Evidence sources">
      <header class="card-header">
        <h3>Sources <span class="badge">${sources.length}</span></h3>
      </header>
      <div class="sources-list">
        ${sources.map((src, i) => renderSourceCard(src, i)).join('\n')}
      </div>
    </aside>
  `;
}

function renderSourceCard(src, index) {
  const snippet = src.content
    ? esc(src.content.length > 240 ? src.content.slice(0, 240) + '…' : src.content)
    : '';

  return `
    <div
      class="source-card"
      id="src-${esc(src.id)}"
      data-source-card="${esc(src.id)}"
    >
      <div class="source-num" aria-hidden="true">${index + 1}</div>
      <div class="source-body">
        <div class="source-title">
          ${src.url
            ? `<a href="${esc(src.url)}" target="_blank" rel="noopener noreferrer">${esc(src.title)}</a>`
            : esc(src.title)
          }
        </div>
        <div class="source-meta">
          ${src.domain ? `<span class="source-tag source-domain">${esc(src.domain)}</span>` : ''}
          ${src.tool   ? `<span class="source-tag source-tool">${esc(src.tool)}</span>`     : ''}
          ${src.author ? `<span class="source-author">${esc(src.author)}</span>`             : ''}
          ${src.score > 0
            ? `<span class="source-score" title="Relevance score (0–1)">Score: ${src.score.toFixed(2)}</span>`
            : ''}
        </div>
        ${snippet ? `<p class="source-snippet">${snippet}</p>` : ''}
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Sort SectionDTOs to match the plan's section order.
 * Falls back to the original array order if no plan is available.
 *
 * @param {SectionDTO[]|null|undefined} sections
 * @param {{ sections?: Array<{ id: string, order: number }> }|null|undefined} plan
 * @returns {SectionDTO[]}
 */
function sortSections(sections, plan) {
  if (!Array.isArray(sections)) return [];
  if (!plan?.sections?.length) return sections;

  const orderMap = {};
  plan.sections.forEach((ps, i) => { orderMap[ps.id] = ps.order ?? i; });

  return [...sections].sort((a, b) => {
    const oa = orderMap[a.spec_id] ?? 999;
    const ob = orderMap[b.spec_id] ?? 999;
    return oa - ob;
  });
}
