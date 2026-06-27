/**
 * API client for the Synapse AI Agent backend.
 *
 * Change API_BASE to point at your running FastAPI instance.
 * Default: https://synapseaiagent-production.up.railway.app
 *
 * No secrets or API keys are present in this file.
 * All communication uses standard fetch / EventSource.
 */

import { authHeader, clearToken, getToken } from './auth.js';

export const API_BASE = 'https://synapseaiagent-production.up.railway.app';

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
 * Thin fetch wrapper: sets Content-Type, injects auth header when authenticated,
 * checks status, and throws ApiError on failure.
 *
 * On a 401 response the stored token is cleared and a `synapse:unauthorized`
 * event is dispatched before the error is thrown — this lets app.js redirect
 * to the login screen without polling.
 *
 * @param {string}      url
 * @param {RequestInit} [options]
 * @param {boolean}     [authenticated=true]  Pass false for login/register calls
 *                                             that have no token yet.
 * @returns {Promise<unknown>}
 */
async function _fetch(url, options = {}, authenticated = true) {
  const resp = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(authenticated ? authHeader() : {}),
      ...(options.headers ?? {}),
    },
  });
  const body = await _parseBody(resp);
  if (!resp.ok) {
    if (resp.status === 401) {
      clearToken();
      window.dispatchEvent(new Event('synapse:unauthorized'));
    }
    throw new ApiError(resp.status, body);
  }
  return body;
}

// ---------------------------------------------------------------------------
// Auth endpoints
// ---------------------------------------------------------------------------

/**
 * POST /auth/register — create a new account.
 * @param {{ email: string, password: string, display_name?: string }} params
 * @returns {Promise<{ access_token: string, token_type: string }>}
 */
export async function register({ email, password, display_name }) {
  return _fetch(
    `${API_BASE}/auth/register`,
    { method: 'POST', body: JSON.stringify({ email, password, display_name }) },
    false,
  );
}

/**
 * POST /auth/login — exchange credentials for a JWT.
 * @param {{ email: string, password: string }} params
 * @returns {Promise<{ access_token: string, token_type: string }>}
 */
export async function login({ email, password }) {
  return _fetch(
    `${API_BASE}/auth/login`,
    { method: 'POST', body: JSON.stringify({ email, password }) },
    false,
  );
}

/**
 * GET /auth/me — return the currently authenticated user.
 * @returns {Promise<{ id: string, email: string, display_name?: string }>}
 */
export async function getMe() {
  return _fetch(`${API_BASE}/auth/me`);
}

// ---------------------------------------------------------------------------
// Dashboard endpoints
// ---------------------------------------------------------------------------

/**
 * GET /dashboard/runs — paginated run history for the current user.
 *
 * @param {{ page?: number, limit?: number, status?: string }} [params]
 * @returns {Promise<{ runs: RunSummary[], total: number }>}
 *
 * RunSummary: { id, query, status, created_at, duration_seconds, has_report }
 */
export async function getDashboardRuns({ page = 1, limit = 20, status } = {}) {
  const qs = new URLSearchParams({ page: String(page), limit: String(limit) });
  if (status) qs.set('status', status);
  return _fetch(`${API_BASE}/dashboard/runs?${qs}`);
}

/**
 * GET /dashboard/runs/{runId}/report — retrieve a stored report.
 *
 * @param {string} runId
 * @returns {Promise<StoredReport>}
 *
 * StoredReport: { title, created_at, content, section_count?, source_count? }
 */
export async function getStoredReport(runId) {
  return _fetch(`${API_BASE}/dashboard/runs/${encodeURIComponent(runId)}/report`);
}

/**
 * GET /dashboard/analytics — aggregate stats for the current user.
 *
 * @returns {Promise<{ total_runs, completed_runs, avg_duration_seconds, avg_sources_per_run }>}
 */
export async function getAnalytics() {
  return _fetch(`${API_BASE}/dashboard/analytics`);
}

// ---------------------------------------------------------------------------
// Public API surface (research pipeline)
// ---------------------------------------------------------------------------

/**
 * GET /healthz
 * @returns {Promise<{ status: string, service: string }>}
 */
export async function healthCheck() {
  return _fetch(`${API_BASE}/healthz`, {}, false);
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
 * EventSource cannot send Authorization headers, so the JWT is appended as a
 * query-string parameter: ?token=<encoded-jwt>.
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
  const token = getToken();
  const url = `${API_BASE}/runs/${encodeURIComponent(threadId)}/stream${token ? `?token=${encodeURIComponent(token)}` : ''}`;
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
