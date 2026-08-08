import { InjectionToken } from '@angular/core';

/**
 * Where the edge lives.
 *
 * The front end and the backend are not deployed together and never will be:
 * the pipeline needs a GPU and lives on a desktop, while this is static files
 * on free hosting. So the address is configuration rather than a relative
 * path, and it changes per deployment.
 *
 * The default is the local backend, which is what it should be while
 * developing. A deployment overrides it in `app.config.ts`. Getting it wrong
 * shows as `offline` rather than as a broken page, because an address that
 * answers nothing is indistinguishable from a machine that is switched off,
 * and both mean the same thing to somebody looking at the screen.
 *
 * No trailing slash: callers join with a leading one.
 */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL', {
  providedIn: 'root',
  factory: () => 'http://127.0.0.1:8000',
});
