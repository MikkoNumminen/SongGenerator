import { describe, expect, it } from 'vitest';

import { EXPIRY_SKEW_MS, isExpired, readClaims } from './id-token';

/** A JWT-shaped string. The signature is never checked here, so it is noise. */
function token(payload: unknown, signature = 'not-checked'): string {
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `header.${body}.${signature}`;
}

describe('reading an ID token', () => {
  it('reads the address and expiry', () => {
    const claims = readClaims(token({ email: 'owner@example.invalid', exp: 1_800_000_000 }));

    expect(claims).toEqual({ email: 'owner@example.invalid', exp: 1_800_000_000 });
  });

  it('keeps a name when there is one, and omits it when there is not', () => {
    expect(readClaims(token({ email: 'a@b.invalid', exp: 1, name: 'Owner' }))?.name)
      .toBe('Owner');
    expect(readClaims(token({ email: 'a@b.invalid', exp: 1 }))?.name).toBeUndefined();
  });

  it('decodes base64url, not base64', () => {
    // Real Google payloads routinely contain characters that encode to - and
    // _, and atob rejects those without translation.
    const email = 'ÿøñ@example.invalid';

    expect(readClaims(token({ email, exp: 1 }))?.email).toBe(email);
  });

  it.each([
    ['not a jwt at all', 'nonsense'],
    ['too few segments', 'header.payload'],
    ['a payload that is not base64', 'header.!!!.sig'],
    ['a payload that is not JSON', `header.${btoa('hello')}.sig`],
  ])('returns null rather than throwing for %s', (_why, bad) => {
    // Anything reaching here came from a script or from storage, and both can
    // hold rubbish. Recovering means signing in again, not crashing.
    expect(() => readClaims(bad)).not.toThrow();
    expect(readClaims(bad)).toBeNull();
  });

  it('refuses a token with no address or no expiry', () => {
    // Without an expiry a dead token would be sent as though it were live.
    expect(readClaims(token({ exp: 1 }))).toBeNull();
    expect(readClaims(token({ email: 'a@b.invalid' }))).toBeNull();
  });
});

describe('deciding a token is spent', () => {
  const at = (secondsFromNow: number) => ({
    email: 'a@b.invalid',
    exp: Math.floor(Date.now() / 1000) + secondsFromNow,
  });

  it('accepts one with time left', () => {
    expect(isExpired(at(3600))).toBe(false);
  });

  it('rejects one that is already past', () => {
    expect(isExpired(at(-1))).toBe(true);
  });

  it('rejects one about to die in flight', () => {
    // A token that expires mid-request comes back 401, which reads to the
    // person as being thrown out rather than as a session ending.
    expect(isExpired(at(Math.floor(EXPIRY_SKEW_MS / 1000) - 1))).toBe(true);
  });
});
