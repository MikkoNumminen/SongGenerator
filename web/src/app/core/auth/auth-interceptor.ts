import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { tap } from 'rxjs';

import { API_BASE_URL } from '../api/api-config';
import { AUTH_CONTEXT } from '../ports/auth-context.port';
import { Membership } from './membership';

/**
 * Attach the bearer token to requests going to the edge, and to nothing else.
 *
 * Scoped to the configured base URL on purpose. An interceptor that attached
 * the token to every outgoing request would hand somebody's Google identity
 * to whatever other host a future feature happens to call, which is the kind
 * of leak that never shows up in testing because it works perfectly.
 *
 * `/health` deliberately goes out without one. It is the route that answers
 * whether the machine is on, it is open by design, and sending credentials to
 * it would make a switched-off desktop look like a sign-in problem.
 */
export const attachBearerToken: HttpInterceptorFn = (request, next) => {
  const baseUrl = inject(API_BASE_URL);
  const auth = inject(AUTH_CONTEXT, { optional: true });
  const membership = inject(Membership);

  const goingToTheEdge = baseUrl !== '' && request.url.startsWith(baseUrl);
  const isHealth = request.url === `${baseUrl}/health`;
  // Routes that answer a stranger on purpose, so their answer says nothing
  // about whether this account has been admitted. Asking for access is the
  // one that mattered: it answers 202, and counting that as a success marked
  // the person admitted the instant they asked, which took away the very
  // screen they were standing on.
  const provesNothing = request.url.startsWith(`${baseUrl}/access-requests`);
  const token = auth?.token() ?? null;

  if (!goingToTheEdge || isHealth || token === null) {
    return next(request);
  }
  // Whether this account has been let in is learned from the answers to
  // requests being made anyway, rather than by asking a question of its own.
  // Every route but /health refuses a stranger, so the first one to come back
  // settles it.
  const carried = next(
    request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }),
  );
  if (provesNothing) {
    return carried;
  }
  return carried.pipe(
    tap({
      next: (event) => {
        const status = (event as { status?: number }).status;
        if (typeof status === 'number') {
          membership.saw(status);
        }
      },
      error: (failure: { status?: number }) => {
        if (typeof failure.status === 'number') {
          membership.saw(failure.status);
        }
      },
    }),
  );
};
