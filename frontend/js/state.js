/**
 * Minimal reactive store using a pub/sub pattern.
 *
 * Usage:
 *   const store = createStore({ count: 0 });
 *   store.subscribe(state => console.log(state));
 *   store.setState({ count: 1 });
 *   store.setState(prev => ({ count: prev.count + 1 }));
 */

/**
 * @template S
 * @param {S} initialState
 * @returns {{
 *   getState: () => S,
 *   setState: (update: Partial<S> | ((prev: S) => Partial<S>)) => void,
 *   subscribe: (listener: (state: S) => void) => () => void,
 * }}
 */
export function createStore(initialState) {
  /** @type {S} */
  let state = Object.assign({}, initialState);
  /** @type {Set<(state: S) => void>} */
  const listeners = new Set();

  return {
    getState() {
      return state;
    },

    setState(update) {
      const patch = typeof update === 'function' ? update(state) : update;
      state = Object.assign({}, state, patch);
      listeners.forEach(fn => fn(state));
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
