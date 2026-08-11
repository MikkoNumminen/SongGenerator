import { DOCUMENT } from '@angular/common';
import { DestroyRef, Injectable, NgZone, inject } from '@angular/core';

import { AUTH_CONTEXT } from '../ports/auth-context.port';

/** How long a session survives with nobody touching it. */
export const IDLE_LIMIT_MS = 30 * 60 * 1000;

/**
 * Sign out after half an hour of nobody being there.
 *
 * The session otherwise lasts as long as the tab and the token, and this is a
 * service that spends somebody's GPU on request. A machine left on a signed-in
 * page in a shared room is the case worth closing.
 *
 * Idle means no input, not "the tab is in the background". A render takes
 * minutes and people quite reasonably go and do something else while the page
 * polls, so hiding the tab must not end the session. Returning to a visible
 * tab counts as activity, since somebody is plainly there.
 *
 * The listeners are passive and run outside Angular. They fire on every
 * pointer move and keypress, and a change detection pass on each would be a
 * measurable cost for something that only ever writes a number.
 */
@Injectable({ providedIn: 'root' })
export class IdleSignOut {
  private readonly auth = inject(AUTH_CONTEXT);
  private readonly zone = inject(NgZone);
  private readonly document = inject(DOCUMENT);
  private readonly destroyRef = inject(DestroyRef);

  private lastSeen = Date.now();
  private timer: ReturnType<typeof setInterval> | null = null;

  /** Begin watching. Called once, by the shell. */
  start(limitMs: number = IDLE_LIMIT_MS): void {
    if (this.timer !== null) {
      return;
    }
    const seen = () => (this.lastSeen = Date.now());
    const events = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;

    this.zone.runOutsideAngular(() => {
      for (const name of events) {
        this.document.addEventListener(name, seen, { passive: true });
      }
      this.document.addEventListener('visibilitychange', () => {
        if (!this.document.hidden) {
          seen();
        }
      });

      // Checked on a coarse interval rather than by scheduling a timeout for
      // the exact moment. A machine that sleeps stops timers, and a session
      // must not survive being asleep for an hour just because the timer it
      // was waiting on never fired. This asks the clock instead.
      this.timer = setInterval(() => {
        if (!this.auth.user()) {
          return;
        }
        if (Date.now() - this.lastSeen >= limitMs) {
          this.zone.run(() => this.auth.signOut());
        }
      }, 30_000);
    });

    this.destroyRef.onDestroy(() => {
      for (const name of events) {
        this.document.removeEventListener(name, seen);
      }
      if (this.timer !== null) {
        clearInterval(this.timer);
        this.timer = null;
      }
    });
  }
}
