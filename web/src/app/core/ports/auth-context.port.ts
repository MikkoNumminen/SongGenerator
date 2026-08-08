import { InjectionToken, Signal } from '@angular/core';

/**
 * Who is asking, and the token that proves it.
 *
 * The service must never be openly usable: the pipeline takes an arbitrary
 * link and spends a GPU on it, so every route but `/health` is behind Google
 * sign-in and an allowlist of specific accounts. Being signed in to Google is
 * not enough, and that check belongs on the server. This port only carries the
 * token there and reports what the browser currently knows.
 *
 * `token()` is deliberately synchronous and nullable rather than a promise.
 * An interceptor needs an answer while building a request, and "there is no
 * token" is a normal answer that should produce an unauthenticated request
 * and a 401, not a hang.
 */
export interface SignedInUser {
  readonly email: string;
  readonly name?: string;
}

export interface AuthContext {
  /** The signed-in account, or null. A signal so views track it. */
  readonly user: Signal<SignedInUser | null>;

  /** The bearer token for the edge, or null when signed out or expired. */
  token(): string | null;

  signIn(): Promise<void>;
  signOut(): void;
}

export const AUTH_CONTEXT = new InjectionToken<AuthContext>('AuthContext');
