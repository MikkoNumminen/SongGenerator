import { HttpErrorResponse } from '@angular/common/http';
import { describe, expect, it } from 'vitest';

import { detailOf, isUnreachable, stateForFailure } from './http-failure';

const failure = (status: number, body?: unknown) =>
  new HttpErrorResponse({ status, error: body, url: 'http://x.invalid/health' });

describe('telling "switched off" apart from "broken"', () => {
  it('treats no response at all as offline', () => {
    // What the browser reports when nothing answered: desktop off, tunnel
    // down, DNS gone, or a preflight that never completed.
    expect(stateForFailure(failure(0))).toEqual({ kind: 'offline' });
  });

  it.each([502, 503, 504])('treats a gateway saying nothing is behind it as offline (%i)', (status) => {
    // Tailscale Funnel in front of a switched-off desktop answers exactly
    // this. It is the most ordinary state this service has.
    expect(stateForFailure(failure(status))).toEqual({ kind: 'offline' });
  });

  it('does NOT treat a server error as offline', () => {
    // Something answered and broke while answering. Calling that "offline"
    // hides a real fault behind a reassuring message.
    expect(stateForFailure(failure(500)).kind).toBe('error');
    expect(isUnreachable(500)).toBe(false);
  });

  it('does not treat being turned away as offline', () => {
    expect(stateForFailure(failure(401, { detail: 'not on the allowlist' })).kind)
      .toBe('error');
  });
});

describe('what the failure says', () => {
  it("keeps the edge's own sentence", () => {
    // These are written for the person reading them, and say which bank is
    // missing or why a link was refused. A generic string throws that away.
    const state = stateForFailure(
      failure(409, { detail: 'a run is already going; this machine takes one at a time' }),
    );

    expect(state).toEqual({
      kind: 'error',
      message: 'a run is already going; this machine takes one at a time',
    });
  });

  it('reads the first field problem out of a validation reply', () => {
    // 422 sends a list rather than a sentence; the rest repeat its shape.
    const body = { detail: [{ loc: ['body', 'source_url'], msg: 'that does not look like a link' }] };

    expect(detailOf(failure(422, body))).toBe('that does not look like a link');
  });

  it('falls back to the status when the body says nothing useful', () => {
    // Better than an empty message, which renders as a blank error box.
    expect(stateForFailure(failure(418, {}))).toEqual({
      kind: 'error',
      message: 'The server answered 418.',
    });
  });

  it('ignores a blank detail rather than showing an empty message', () => {
    expect(detailOf(failure(400, { detail: '   ' }))).toBeUndefined();
  });

  it('survives a body that is not JSON at all', () => {
    // A proxy error page reaches here as an HTML string.
    expect(stateForFailure(failure(500, '<html>gateway</html>')).kind).toBe('error');
  });
});
