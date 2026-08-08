import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { API_BASE_URL } from '../api/api-config';
import { AUTH_CONTEXT } from '../ports/auth-context.port';

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

  const goingToTheEdge = baseUrl !== '' && request.url.startsWith(baseUrl);
  const isHealth = request.url === `${baseUrl}/health`;
  const token = auth?.token() ?? null;

  if (!goingToTheEdge || isHealth || token === null) {
    return next(request);
  }
  return next(
    request.clone({ setHeaders: { Authorization: `Bearer ${token}` } }),
  );
};
