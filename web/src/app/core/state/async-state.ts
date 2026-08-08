/**
 * The states an async view can be in, one at a time.
 *
 * A view that tracks `loading` and `data` as separate fields can be in
 * combinations nobody designed: loading with stale data, done with neither
 * data nor error. Rendering those honestly means a chain of conditionals in
 * every template, and the ones nobody thought about render as blank.
 *
 * `offline` is separate from `error` on purpose, and is the reason this file
 * exists rather than a boolean. The backend is a desktop that is often simply
 * switched off. That is the normal case here, not a fault, and it must never
 * be shown as a broken application.
 *
 * `empty` is separate from `ready` for the same reason one step down: a
 * successful request that returned nothing is a real answer with its own
 * wording ("no runs yet"), not a spinner that never stops.
 */
export type AsyncState<T> =
  | { readonly kind: 'idle' }
  | { readonly kind: 'loading' }
  | { readonly kind: 'ready'; readonly value: T }
  | { readonly kind: 'empty' }
  | { readonly kind: 'error'; readonly message: string }
  | { readonly kind: 'offline' };

/** Nothing has been asked for yet. Distinct from loading: no spinner. */
export const idle = (): AsyncState<never> => ({ kind: 'idle' });

export const loading = (): AsyncState<never> => ({ kind: 'loading' });

export const empty = (): AsyncState<never> => ({ kind: 'empty' });

/** The machine could not be reached. Not an error; usually just switched off. */
export const offline = (): AsyncState<never> => ({ kind: 'offline' });

export const failed = (message: string): AsyncState<never> => ({
  kind: 'error',
  message,
});

export const ready = <T>(value: T): AsyncState<T> => ({ kind: 'ready', value });

/**
 * The value, or undefined in every state that does not have one.
 *
 * Deliberately not a throwing accessor: a template asking for the value of a
 * failed state is a template bug, and blowing up during rendering turns it
 * into a blank page rather than a visible one.
 */
export function valueOf<T>(state: AsyncState<T>): T | undefined {
  return state.kind === 'ready' ? state.value : undefined;
}
