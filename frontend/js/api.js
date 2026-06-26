/**
 * API client for the Synapse AI Agent backend.
 *
 * Change API_BASE to point at your running FastAPI instance.
 * Default: http://localhost:8000
 *
 * No secrets or API keys are present in this file.
 * All communication uses standard fetch / EventSource.
 */

export const API_BASE = 'http://localhost:8000';

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

/**
 * Wraps a non-2xx HTTP response. Carries the HTTP status and the parsed body.
 */
export class ApiError extends Error {
  /**
   * @param {number} status
   * @param {unknown} body   Parsed JSON body (or a plain object with an `error` key).
   */
  constructor(status, body) {
    const message =
      (typeof body === 'object' && body !== null
        ? body.error ||
          (Array.isArray(body.detail)
            ? body.detail.map(d => d.msg || JSON.stringify(d)).join('; ')
            : body.detail)
        : null) ||
      `HTTP ${status}`;
    super(String(message));
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Parse a Response as JSON, falling back to a text-based error object. */
async function _parseBody(resp) {
  const text = await resp.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { error: text };
  }
}

/**
 * Thin fetch wrapper: sets Content-Type, checks status, throws ApiError on failure.
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<unknown>}
 */
async function _fetch(url, options = {}) {
  const resp = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers ?? {}),
    },
  });
  const body = await _parseBody(resp);
  if (!resp.ok) throw new ApiError(resp.status, body);
  return body;
}

// ---------------------------------------------------------------------------
// Public API surface
// ---------------------------------------------------------------------------

/**
 * GET /healthz
 * @returns {Promise<{ status: string, service: string }>}
 */
export async function healthCheck() {
  return _fetch(`${API_BASE}/healthz`);
}

/**
 * POST /runs  — start a new research run.
 *
 * @param {{
 *   query: string,
 *   max_retrieval_iterations?: number|null,
 *   max_revise_iterations?: number|null
 * }} params
 * @returns {Promise<RunResponse>}
 *
 * RunResponse: { thread_id, status, plan?, interrupt_payload? }
 */
export async function startRun({ query, max_retrieval_iterations, max_revise_iterations }) {
  /** @type {Record<string,unknown>} */
  const body = { query };
  if (max_retrieval_iterations != null) body.max_retrieval_iterations = max_retrieval_iterations;
  if (max_revise_iterations != null) body.max_revise_iterations = max_revise_iterations;

  return _fetch(`${API_BASE}/runs`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * POST /runs/{thread_id}/resume  — resume a paused run.
 *
 * @param {string} threadId
 * @param {{
 *   action: 'approve'|'edit'|'reject',
 *   edited_plan?: {
 *     audience: string, length: string, tone: string,
 *     sections: Array<{ id: string, heading: string, intent: string, order: number }>
 *   }|null
 * }} params
 * @returns {Promise<ResumeResponse>}
 *
 * ResumeResponse: { thread_id, status, report?, final_answer?, sections?,
 *                   low_confidence?, sources?, plan?, interrupt_payload? }
 */
export async function resumeRun(threadId, { action, edited_plan }) {
  /** @type {Record<string,unknown>} */
  const body = { action };
  if (edited_plan != null) body.edited_plan = edited_plan;

  return _fetch(`${API_BASE}/runs/${encodeURIComponent(threadId)}/resume`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

/**
 * GET /runs/{thread_id}  — fetch current status from the checkpointer.
 *
 * @param {string} threadId
 * @returns {Promise<StatusResponse>}
 *
 * StatusResponse: { thread_id, status, plan?, report?, final_answer?,
 *                   sections?, low_confidence?, sources?, next_nodes[] }
 */
export async function getRunStatus(threadId) {
  return _fetch(`${API_BASE}/runs/${encodeURIComponent(threadId)}`);
}

/**
 * GET /runs/{thread_id}/stream  — open an SSE stream of checkpoint-history events.
 *
 * Events are emitted most-recent-first by the backend (get_state_history order).
 * Closes automatically on "done" or "not_found" events.
 *
 * @param {string} threadId
 * @param {{
 *   onEvent?: (data: CheckpointEvent) => void,
 *   onDone?:  (data: { event: string, thread_id: string, total_checkpoints?: number }) => void,
 *   onError?: (data: { error: string }) => void,
 * }} callbacks
 * @returns {{ close: () => void }}
 *
 * CheckpointEvent: { event, thread_id, status, step, node, next[],
 *                    has_report, has_final_answer, low_confidence }
 */
export function streamRun(threadId, { onEvent, onDone, onError } = {}) {
  const url = `${API_BASE}/runs/${encodeURIComponent(threadId)}/stream`;
  const es = new EventSource(url);

  es.onmessage = (e) => {
    let data;
    try {
      data = JSON.parse(e.data);
    } catch {
      // Malformed SSE data — skip silently
      return;
    }

    const ev = data.event;
    if (ev === 'done' || ev === 'not_found') {
      es.close();
      if (onDone) onDone(data);
    } else if (ev === 'error') {
      es.close();
      if (onError) onError({ error: data.error || 'Stream error' });
    } else if (ev === 'checkpoint') {
      if (onEvent) onEvent(data);
    }
    // Unknown event types are ignored
  };

  es.onerror = () => {
    es.close();
    if (onError) onError({ error: 'SSE connection failed or server unavailable during pipeline run' });
  };

  return { close: () => es.close() };
}
