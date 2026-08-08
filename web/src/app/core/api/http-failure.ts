import { HttpErrorResponse } from '@angular/common/http';

import { AsyncState, failed, offline } from '../state/async-state';

/**
 * Statuses that mean "nothing answered", rather than "something answered and
 * said no".
 *
 * 0 is what the browser reports when there was no HTTP response at all: the
 * desktop is off, the tunnel is down, DNS failed, or the CORS preflight never
 * completed. It is indistinguishable from a network cable being out, and all
 * of those are "come back later" rather than "something is broken".
 *
 * 502, 503 and 504 are the same answer one hop further out: the tunnel is up
 * and reachable, and the machine behind it is not. Tailscale Funnel in front
 * of a switched-off desktop produces exactly this, so treating it as an error
 * would show a fault for the most ordinary state this service has.
 *
 * 500 is deliberately NOT here. Something did answer, and it broke while
 * answering. Reporting that as "offline" would hide a real fault behind a
 * reassuring message and leave nobody looking for it.
 */
const UNREACHABLE = new Set([0, 502, 503, 504]);

export function isUnreachable(status: number): boolean {
  return UNREACHABLE.has(status);
}

/**
 * The message the edge sent, if it sent one.
 *
 * FastAPI puts a readable sentence in `detail`, and those sentences are
 * written for the person reading them: which bank is missing, that a run is
 * already going, why a link was refused. Replacing them with a generic string
 * would throw away the most useful thing in the response.
 */
export function detailOf(error: HttpErrorResponse): string | undefined {
  const body: unknown = error.error;
  // A plain-string body is deliberately ignored. The edge always answers with
  // JSON, so a string came from something in between: a tunnel or a proxy,
  // whose body is usually a full HTML page. Passing that through put markup
  // in front of the reader as if the server had written them a sentence.
  if (body && typeof body === 'object' && 'detail' in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === 'string' && detail.trim() !== '') {
      return detail;
    }
    // 422 sends a list of field problems rather than a sentence. The first one
    // is the useful one; the rest repeat its shape.
    if (Array.isArray(detail) && detail.length > 0) {
      const first: unknown = detail[0];
      if (first && typeof first === 'object' && 'msg' in first) {
        const msg = (first as { msg: unknown }).msg;
        if (typeof msg === 'string') {
          return msg;
        }
      }
    }
  }
  return undefined;
}

/**
 * Turn a failed request into the state a view should render.
 *
 * Every caller goes through this rather than deciding per feature, because
 * "is the desktop off" is one judgement and two features answering it
 * differently is how one screen says "switched off" while another shows a
 * stack trace for the same cause.
 */
export function stateForFailure(error: HttpErrorResponse): AsyncState<never> {
  if (isUnreachable(error.status)) {
    return offline();
  }
  return failed(detailOf(error) ?? `The server answered ${error.status}.`);
}
