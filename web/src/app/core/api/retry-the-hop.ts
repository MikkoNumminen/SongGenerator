import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Observable, retry, throwError, timer } from 'rxjs';

/**
 * Try a read again when the hop in front of the edge drops it.
 *
 * The site reaches the backend through a proxy on another host, and that hop
 * loses requests. Measured, twice, on separate days: about four in twenty
 * answered 502 through the proxy while twenty of twenty succeeded called
 * directly, so the backend is fine and the path to it is not. Left alone, one
 * request in five fails and the application looks broken to the person using
 * it.
 *
 * Only GET. A retry is safe when the request is a question and unsafe when it
 * is an instruction: POST /jobs starts a render on a GPU, and answering a
 * dropped connection by starting a second one is worse than reporting the
 * first as failed.
 *
 * Only the statuses that hop produces. 502, 503 and 504 also mean "that
 * desktop is switched off", which is this service's most ordinary state, so
 * retrying costs about a second before the honest message appears. That is
 * the price of recovering the four in twenty, and it is worth it: the
 * switched-off case still ends in the same panel, one beat later.
 *
 * Status 0 is deliberately not retried. It is a browser refusing the request
 * outright, from CORS or from having no network at all, and repeating it
 * changes nothing except how long somebody waits to be told.
 */
const RETRY_STATUSES = new Set([502, 503, 504]);

/** Retries, not attempts: two of these means three tries in all. Beyond that
 * the hop is not flaky, it is down, and waiting longer only delays saying so. */
const RETRIES = 2;
const FIRST_DELAY_MS = 300;

export const retryTheHop: HttpInterceptorFn = (request, next) => {
  if (request.method !== 'GET') {
    return next(request);
  }
  return next(request).pipe(
    retry({
      count: RETRIES,
      delay: (error: unknown, attempt: number): Observable<number> => {
        const failure = error as HttpErrorResponse;
        if (!RETRY_STATUSES.has(failure?.status)) {
          return throwError(() => error);
        }
        // 300ms then 900ms. Long enough that a second attempt is not part of
        // the same hiccup, short enough that a person waiting on a list does
        // not notice the difference.
        return timer(FIRST_DELAY_MS * 3 ** (attempt - 1));
      },
    }),
  );
};
