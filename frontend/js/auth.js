/**
 * Token storage and auth utilities for Synapse AI Agent.
 *
 * No imports needed — this module is the root of the auth dependency chain.
 * api.js imports from here; nothing in this file imports from other app modules.
 */

const TOKEN_KEY = 'synapse_token';

export const getToken  = ()  => localStorage.getItem(TOKEN_KEY);
export const setToken  = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);
export const isAuthed  = ()  => !!getToken();

/**
 * Returns an object with the Authorization header if a token is stored,
 * or an empty object if not.  Spread into fetch headers.
 * @returns {{ Authorization: string } | {}}
 */
export const authHeader = () =>
  getToken() ? { Authorization: `Bearer ${getToken()}` } : {};

/**
 * Remove the token and dispatch `synapse:logout` so any listener
 * (app.js) can redirect to the login screen.
 */
export const logout = () => {
  clearToken();
  window.dispatchEvent(new Event('synapse:logout'));
};
