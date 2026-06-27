/**
 * Login / Register view.
 *
 * Renders a centred auth card with two modes toggled by an inline link:
 *   "Login"    — POST /auth/login    via api.js login()
 *   "Register" — POST /auth/register via api.js register()
 *
 * On success the token is stored via setToken() and onSuccess() is called.
 * Inline error messages are shown below the form for bad credentials,
 * duplicate email, etc.
 *
 * @param {HTMLElement} container
 * @param {() => void | Promise<void>} onSuccess  Called after token is stored.
 */

import { login, register } from './api.js';
import { setToken }        from './auth.js';
import { esc }             from './utils.js';

export function renderLoginView(container, onSuccess) {
  /** @type {'login'|'register'} */
  let mode = 'login';

  // -------------------------------------------------------------------------
  // HTML builders
  // -------------------------------------------------------------------------

  function renderLoginFields() {
    return `
      <h2 class="auth-form-title">Sign In</h2>
      <form id="auth-form" novalidate>
        <div class="field">
          <label for="auth-email">Email</label>
          <input
            type="email"
            id="auth-email"
            name="email"
            autocomplete="email"
            required
            aria-required="true"
            placeholder="you@example.com"
          >
        </div>
        <div class="field">
          <label for="auth-password">Password</label>
          <input
            type="password"
            id="auth-password"
            name="password"
            autocomplete="current-password"
            required
            aria-required="true"
            placeholder="Password"
          >
        </div>
        <div id="auth-error" class="error-inline" hidden role="alert" aria-live="assertive"></div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary auth-submit-btn" id="auth-submit">
            Sign In
          </button>
        </div>
      </form>
      <p class="auth-toggle">
        Don't have an account?
        <a href="#" id="toggle-mode" aria-label="Switch to registration form">Register</a>
      </p>
    `;
  }

  function renderRegisterFields() {
    return `
      <h2 class="auth-form-title">Create Account</h2>
      <form id="auth-form" novalidate>
        <div class="field">
          <label for="auth-email">Email</label>
          <input
            type="email"
            id="auth-email"
            name="email"
            autocomplete="email"
            required
            aria-required="true"
            placeholder="you@example.com"
          >
        </div>
        <div class="field">
          <label for="auth-display-name">Display name <span class="muted">(optional)</span></label>
          <input
            type="text"
            id="auth-display-name"
            name="display_name"
            autocomplete="name"
            placeholder="Your name"
          >
        </div>
        <div class="field">
          <label for="auth-password">Password</label>
          <input
            type="password"
            id="auth-password"
            name="password"
            autocomplete="new-password"
            required
            aria-required="true"
            placeholder="Choose a password"
          >
        </div>
        <div id="auth-error" class="error-inline" hidden role="alert" aria-live="assertive"></div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary auth-submit-btn" id="auth-submit">
            Create Account
          </button>
        </div>
      </form>
      <p class="auth-toggle">
        Already have an account?
        <a href="#" id="toggle-mode" aria-label="Switch to login form">Sign in</a>
      </p>
    `;
  }

  function renderCard() {
    container.innerHTML = `
      <div class="view view-auth">
        <div class="auth-card" role="main">
          <div class="auth-brand" aria-hidden="true">
            <span class="brand-mark">&#9672;</span>
            <span class="auth-brand-name">Synapse</span>
          </div>
          <p class="auth-brand-sub">AI Research Agent</p>
          ${mode === 'login' ? renderLoginFields() : renderRegisterFields()}
        </div>
      </div>
    `;
    wireCard();
  }

  // -------------------------------------------------------------------------
  // Event wiring
  // -------------------------------------------------------------------------

  function wireCard() {
    // Mode toggle
    const toggleLink = container.querySelector('#toggle-mode');
    if (toggleLink) {
      toggleLink.addEventListener('click', (e) => {
        e.preventDefault();
        mode = mode === 'login' ? 'register' : 'login';
        renderCard();
      });
    }

    // Form submission
    const form      = container.querySelector('#auth-form');
    const errorEl   = container.querySelector('#auth-error');
    const submitBtn = container.querySelector('#auth-submit');

    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      errorEl.hidden = true;
      submitBtn.disabled = true;
      const labelOriginal = submitBtn.textContent;
      submitBtn.textContent = mode === 'login' ? 'Signing in…' : 'Creating account…';

      const email    = (container.querySelector('#auth-email')?.value ?? '').trim();
      const password = container.querySelector('#auth-password')?.value ?? '';

      if (!email || !password) {
        showError('Email and password are required.');
        submitBtn.disabled = false;
        submitBtn.textContent = labelOriginal;
        return;
      }

      try {
        let data;
        if (mode === 'login') {
          data = await login({ email, password });
        } else {
          const display_name = (container.querySelector('#auth-display-name')?.value ?? '').trim();
          data = await register({ email, password, display_name: display_name || undefined });
        }

        if (!data?.access_token) {
          throw new Error('No access token in server response.');
        }

        setToken(data.access_token);
        // onSuccess may be async (it calls getMe() in app.js); fire and forget from here
        onSuccess();
      } catch (err) {
        let msg = 'Authentication failed. Please try again.';
        if (err?.body) {
          const b = err.body;
          msg =
            b.detail && !Array.isArray(b.detail) ? String(b.detail) :
            Array.isArray(b.detail) ? b.detail.map(d => d.msg ?? JSON.stringify(d)).join('; ') :
            b.error ? String(b.error) :
            err.message || msg;
        } else if (err instanceof Error) {
          msg = err.message;
        }
        showError(msg);
        submitBtn.disabled = false;
        submitBtn.textContent = labelOriginal;
      }
    });

    // Auto-focus first field
    container.querySelector('#auth-email')?.focus();
  }

  function showError(msg) {
    const el = container.querySelector('#auth-error');
    if (!el) return;
    el.textContent = msg;
    el.hidden = false;
    el.focus();
  }

  // Initial render
  renderCard();
}
