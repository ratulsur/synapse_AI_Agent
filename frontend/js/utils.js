/**
 * Shared utilities for the Synapse AI Agent frontend.
 */

/**
 * Escape a value for safe insertion as HTML text content.
 * @param {unknown} str
 * @returns {string}
 */
export function esc(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * Format an error (ApiError, Error, string, or plain object) into a display string.
 * @param {unknown} err
 * @returns {{ message: string, detail: string }}
 */
export function formatError(err) {
  if (!err) return { message: 'An unknown error occurred.', detail: '' };

  // ApiError from api.js
  if (err && err.body) {
    const b = err.body;
    const message =
      b.error ||
      (Array.isArray(b.detail)
        ? b.detail.map(d => d.msg || JSON.stringify(d)).join('; ')
        : b.detail) ||
      err.message ||
      `HTTP ${err.status}`;
    const detail = b.type ? `Type: ${b.type}` : '';
    return { message: String(message), detail };
  }

  if (typeof err === 'string') return { message: err, detail: '' };
  if (err instanceof Error) return { message: err.message, detail: '' };
  return { message: String(err), detail: '' };
}
