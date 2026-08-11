import {
  HttpErrorResponse,
  HttpHandlerFn,
  HttpRequest,
  HttpResponse,
} from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, defer, of, throwError } from 'rxjs';
import { describe, expect, it } from 'vitest';

import { retryTheHop } from './retry-the-hop';

/**
 * Runs the interceptor with a handler that fails a given number of times.
 *
 * Real timers, and the delays are short on purpose so the suite does not need
 * fake ones. The alternative is a test that passes because the clock was
 * mocked into agreeing with it.
 */
function run(
  method: 'GET' | 'POST',
  failures: number,
  status: number,
): { result: Promise<unknown>; calls: () => number } {
  let calls = 0;
  // `defer`, because retry resubscribes to the observable the handler
  // returned rather than calling the handler again. Counting invocations of
  // the function instead reported one attempt however many were made, and a
  // cold throwError re-emitted the same failure forever. Angular's real
  // handler re-issues the request on resubscribe; this is what models that.
  const next: HttpHandlerFn = (): Observable<HttpResponse<unknown>> =>
    defer(() => {
      calls += 1;
      return calls <= failures
        ? throwError(() => new HttpErrorResponse({ status }))
        : of(new HttpResponse({ status: 200, body: { ok: true } }));
    });
  const request = new HttpRequest(method, '/x', method === 'POST' ? {} : null);
  const result = TestBed.runInInjectionContext(
    () =>
      new Promise((resolve, reject) =>
        retryTheHop(request as HttpRequest<unknown>, next).subscribe({
          next: resolve,
          error: reject,
        }),
      ),
  );
  return { result, calls: () => calls };
}

describe('retrying the hop in front of the edge', () => {
  it('recovers a read the proxy dropped', async () => {
    // The measured fault: about four requests in twenty answer 502 through
    // the proxy while every one succeeds called directly.
    const { result, calls } = run('GET', 1, 502);

    await expect(result).resolves.toBeInstanceOf(HttpResponse);
    expect(calls()).toBe(2);
  });

  it('gives up after two more attempts rather than hanging on', async () => {
    const { result, calls } = run('GET', 99, 503);

    await expect(result).rejects.toBeInstanceOf(HttpErrorResponse);
    expect(calls()).toBe(3);
  });

  it('never repeats a write', async () => {
    // A retry is safe when the request is a question and unsafe when it is an
    // instruction. POST /jobs starts a render on a GPU; answering a dropped
    // connection by starting a second one is worse than reporting a failure.
    const { result, calls } = run('POST', 1, 502);

    await expect(result).rejects.toBeInstanceOf(HttpErrorResponse);
    expect(calls()).toBe(1);
  });

  it('does not retry a refusal', async () => {
    // 401 and 403 are answers, not drops. Repeating them wastes a second and
    // changes nothing.
    for (const status of [401, 403, 404, 409, 500]) {
      const { result, calls } = run('GET', 99, status);
      await expect(result).rejects.toBeInstanceOf(HttpErrorResponse);
      expect(calls(), `status ${status}`).toBe(1);
    }
  });

  it('does not retry a browser that refused to send it', async () => {
    // Status 0 is CORS or no network. Repeating it changes nothing except how
    // long somebody waits to be told.
    const { result, calls } = run('GET', 99, 0);

    await expect(result).rejects.toBeInstanceOf(HttpErrorResponse);
    expect(calls()).toBe(1);
  });

  it('finishes well inside the poll interval the run watcher uses', async () => {
    // Everything the app reads goes through this, including the poll that
    // follows a render at POLL_MS. The watcher waits for each answer before
    // scheduling the next, so a slow retry cannot stack requests, but it
    // would still stretch the gap between updates if the backoff were long.
    const started = Date.now();
    const { result } = run('GET', 99, 502);
    await expect(result).rejects.toMatchObject({ status: 502 });

    expect(Date.now() - started).toBeLessThan(1_500);
  });

  it('passes a successful read straight through', async () => {
    const { result, calls } = run('GET', 0, 502);

    await expect(result).resolves.toBeInstanceOf(HttpResponse);
    expect(calls()).toBe(1);
  });

  it('still ends in the offline panel when the desktop is simply off', async () => {
    // The cost of retrying: 502 also means "that desktop is switched off",
    // which is the most ordinary state this service has. It still arrives at
    // the same answer, about a second later.
    const started = Date.now();
    const { result } = run('GET', 99, 502);

    await expect(result).rejects.toMatchObject({ status: 502 });
    expect(Date.now() - started).toBeGreaterThanOrEqual(300);
  });
});
