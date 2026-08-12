import { Injectable, effect, inject } from '@angular/core';

import { LIBRARY } from '../ports/library.port';
import { AUTH_CONTEXT } from '../ports/auth-context.port';

/**
 * Fetch what the session will need as soon as there is somebody to fetch for.
 *
 * Signing in is the moment the answers become gettable and the moment somebody
 * starts clicking, so the two race: the first page reached would be the one
 * that paid for the fetch, and every later page paid again on arrival. Asking
 * once here means the first page usually finds the answer already in hand and
 * draws immediately.
 *
 * Signing out throws it away. The next person at this browser is not
 * necessarily the same person, and two accounts do not see the same library.
 */
@Injectable({ providedIn: 'root' })
export class Prime {
  private readonly auth = inject(AUTH_CONTEXT, { optional: true });
  private readonly library = inject(LIBRARY);
  private primedFor: string | null = null;

  /** Begin watching. Called once, by the shell. */
  start(): void {
    effect(() => {
      const who = this.auth?.user()?.email ?? null;

      if (who === null) {
        if (this.primedFor !== null) {
          this.library.forget();
          this.primedFor = null;
        }
        return;
      }

      if (who !== this.primedFor) {
        // A different account sees a different library, so what was held
        // belongs to the person who left.
        this.library.forget();
        this.primedFor = who;
        // Nothing is done with the answer here. Asking is the point: it lands
        // in the cache, and the page that wants it finds it already there.
        this.library.list().subscribe({ error: () => undefined });
      }
    });
  }
}
