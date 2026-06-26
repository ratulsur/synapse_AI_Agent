/**
 * Minimal Markdown -> HTML renderer for LLM-generated report content.
 *
 * Handles: headings (#–######), bold/italic/inline-code, links,
 * unordered and ordered lists, horizontal rules, and paragraphs.
 * HTML is escaped before inline transformations to prevent XSS.
 */

function escHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Apply inline Markdown formatting on an already-HTML-escaped string.
 * Order: triple > double > single asterisk/underscore, then code, then links.
 * @param {string} text  Raw (unescaped) text fragment.
 * @returns {string}     HTML string.
 */
function inlineFormat(text) {
  return escHtml(text)
    // Bold-italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    // Bold
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // Italic (* or _)
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/_([^_]+?)_/g, '<em>$1</em>')
    // Inline code
    .replace(/`(.+?)`/g, '<code>$1</code>')
    // Markdown links [text](url)
    .replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );
}

/**
 * Render Markdown text to an HTML string.
 * @param {string|null|undefined} text
 * @returns {string}
 */
export function renderMarkdown(text) {
  if (!text) return '';

  const lines = text.split('\n');
  const out = [];
  /** @type {string[]} */
  let paraLines = [];
  /** @type {'ul'|'ol'|''} */
  let listTag = '';

  function flushPara() {
    if (paraLines.length > 0) {
      out.push(`<p>${paraLines.map(inlineFormat).join('<br>')}</p>`);
      paraLines = [];
    }
  }

  function flushList() {
    if (listTag) {
      out.push(`</${listTag}>`);
      listTag = '';
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    // Blank line: close any open block
    if (!line.trim()) {
      flushPara();
      flushList();
      continue;
    }

    // ATX Heading: # through ######
    const hm = line.match(/^(#{1,6})\s+(.+)$/);
    if (hm) {
      flushPara();
      flushList();
      const level = hm[1].length;
      out.push(`<h${level}>${inlineFormat(hm[2])}</h${level}>`);
      continue;
    }

    // Horizontal rule: ---, ***, ___
    if (/^([-*_])\1{2,}\s*$/.test(line.trim())) {
      flushPara();
      flushList();
      out.push('<hr>');
      continue;
    }

    // Unordered list item: - or * or +
    const ulm = line.match(/^[-*+]\s+(.+)$/);
    if (ulm) {
      flushPara();
      if (listTag !== 'ul') {
        flushList();
        out.push('<ul>');
        listTag = 'ul';
      }
      out.push(`<li>${inlineFormat(ulm[1])}</li>`);
      continue;
    }

    // Ordered list item: 1. 2. etc.
    const olm = line.match(/^\d+\.\s+(.+)$/);
    if (olm) {
      flushPara();
      if (listTag !== 'ol') {
        flushList();
        out.push('<ol>');
        listTag = 'ol';
      }
      out.push(`<li>${inlineFormat(olm[1])}</li>`);
      continue;
    }

    // Normal text — accumulate in paragraph buffer
    flushList();
    paraLines.push(line);
  }

  // Flush any remaining content
  flushPara();
  flushList();

  return out.join('\n');
}
