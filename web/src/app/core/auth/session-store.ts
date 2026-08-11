import { Injectable } from '@angular/core';

/**
 * Where a signed-in session survives a page load.
 *
 * Without this the token lived in a field, so every full load signed somebody
 * out: a refresh, a new tab, or following the redirect from the domain that
 * links here. That reads as "it signs me out all the time", and it is not
 * about how long a session lasts.
 *
 * `sessionStorage`, not `localStorage`. It is scoped to the one tab and goes
 * when the tab does, which bounds what a stolen token could be used from and
 * matches how this service is actually used: opened, listened to, closed.
 * A Google id token is good for about an hour anyway, so persisting it beyond
 * the tab would buy very little and widen the blast radius of any script that
 * ever got onto the page.
 *
 * Every access is wrapped. Storage throws rather than returning null in a
 * private window, when a quota is full, and when a browser is configured to
 * refuse it; an application that cannot sign anybody in because reading a
 * cache threw is a worse outcome than one that simply asks again.
 */
const KEY = 'songgen.session';

@Injectable({ providedIn: 'root' })
export class SessionStore {
  read(): string | null {
    try {
      return sessionStorage.getItem(KEY);
    } catch {
      return null;
    }
  }

  write(token: string): void {
    try {
      sessionStorage.setItem(KEY, token);
    } catch {
      // A session that cannot be remembered still works for this tab.
    }
  }

  clear(): void {
    try {
      sessionStorage.removeItem(KEY);
    } catch {
      // Nothing to do, and nothing worth telling anybody about.
    }
  }
}
