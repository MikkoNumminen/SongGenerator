/**
 * Reading a Google ID token, without believing it.
 *
 * Nothing here is a security check and nothing here may be treated as one.
 * The signature is not verified, because a browser cannot meaningfully verify
 * a token it was handed: whoever controls the page controls the answer. The
 * edge verifies it against Google and checks the address against an allowlist,
 * and that is the check that counts.
 *
 * What this is for is the two things a browser legitimately does with a token
 * it is only carrying: show whose name is on it, and notice that it has
 * expired so it can ask for a new one instead of sending a request that is
 * certain to come back 401.
 */
export interface IdTokenClaims {
  readonly email: string;
  readonly name?: string;
  /** Seconds since the epoch, as JWTs count. */
  readonly exp: number;
}

/** Google ID tokens last an hour; this is the margin against clock drift. */
export const EXPIRY_SKEW_MS = 30_000;

function decodeSegment(segment: string): unknown {
  // base64url, which is base64 with two characters swapped and the padding
  // left off. atob wants neither.
  const base64 = segment.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
  return JSON.parse(atob(padded));
}

/**
 * The claims, or null if this is not a token this app can use.
 *
 * Null rather than throwing: a malformed or truncated token is something to
 * recover from by signing in again, not a crash. Anything reaching here came
 * from a script or from storage, and both can hold rubbish.
 */
export function readClaims(token: string): IdTokenClaims | null {
  const parts = token.split('.');
  if (parts.length !== 3) {
    return null;
  }
  let payload: unknown;
  try {
    payload = decodeSegment(parts[1]);
  } catch {
    return null;
  }
  if (!payload || typeof payload !== 'object') {
    return null;
  }
  const { email, name, exp } = payload as Record<string, unknown>;
  // Both are required to be useful: an address to show, and an expiry so a
  // dead token is not sent as though it were live.
  if (typeof email !== 'string' || email === '' || typeof exp !== 'number') {
    return null;
  }
  return { email, exp, ...(typeof name === 'string' ? { name } : {}) };
}

/**
 * Whether the token is past using.
 *
 * Counted as expired slightly early, because a token that dies in flight
 * comes back as a 401 that looks to the reader like being thrown out rather
 * than like a session ending.
 */
export function isExpired(
  claims: IdTokenClaims,
  now: number = Date.now(),
  skewMs: number = EXPIRY_SKEW_MS,
): boolean {
  return claims.exp * 1000 - skewMs <= now;
}
