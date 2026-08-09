import { InjectionToken } from '@angular/core';

/**
 * Where the edge lives.
 *
 * The front end and the backend are not deployed together and never will be:
 * the pipeline needs a GPU and lives on a desktop, while this is static files
 * on free hosting. So the address is configuration rather than a relative
 * path, and it changes per deployment.
 *
 * Bootstrap always provides this, from the runtime config. The default here is
 * deliberately empty rather than the local backend: a token that quietly falls
 * back to `http://127.0.0.1:8000` is how a deployed page ended up asking for
 * things on the visitor's own machine, and one safe default is worth less than
 * no guess at all. Callers treat an empty address as "not configured" and make
 * no request.
 *
 * No trailing slash: callers join with a leading one.
 */
export const API_BASE_URL = new InjectionToken<string>('API_BASE_URL', {
  providedIn: 'root',
  factory: () => '',
});
