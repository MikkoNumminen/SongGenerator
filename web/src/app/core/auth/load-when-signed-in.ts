import { effect, inject } from '@angular/core';

import { AUTH_CONTEXT } from '../ports/auth-context.port';

/**
 * Fetch when there is somebody to fetch for, and again when that changes.
 *
 * Every route but `/health` is behind sign-in, so a page that loads once in
 * `ngOnInit` asks before anybody has signed in, is refused, and settles into a
 * failure with a "Try again" button. Signing in then changed nothing on screen:
 * the page had already asked and had no reason to ask twice, so the first
 * thing a person did after arriving was press a button to recover from a
 * failure that was only ever a matter of ordering.
 *
 * The identity is a signal, so this watches it instead. Signing in loads.
 * Signing out and back in as somebody else loads again, which matters because
 * two accounts do not see the same library.
 *
 * Call from a field initialiser or a constructor: it needs an injection
 * context, and effects are torn down with the component that made them.
 */
export function loadWhenSignedIn(load: () => void): void {
  const auth = inject(AUTH_CONTEXT);
  let loadedFor: string | null | undefined;

  effect(() => {
    const who = auth.user()?.email ?? null;

    // Where sign-in is not configured at all there is nobody to wait for, and
    // the page should ask once and show whatever the edge says. A clone with
    // no client id is a working read-only deployment, not a broken one.
    if (!auth.configured) {
      if (loadedFor === undefined) {
        loadedFor = null;
        load();
      }
      return;
    }

    // Signed out: nothing to ask for. Asking anyway is the 401 that produced
    // the button this exists to remove.
    if (who === null) {
      loadedFor = null;
      return;
    }

    if (who !== loadedFor) {
      loadedFor = who;
      load();
    }
  });
}
