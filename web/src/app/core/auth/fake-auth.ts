import { Provider, signal } from '@angular/core';

import { AUTH_CONTEXT, SignedInUser } from '../ports/auth-context.port';

/**
 * A signed-in identity for tests, and a handle to change it.
 *
 * Pages fetch when somebody is signed in, so every page test needs an answer
 * to "who is asking". Three specs were writing their own version of this one;
 * the shared one also lets a test sign somebody in halfway through, which is
 * the case worth covering.
 */
export interface FakeAuth {
  readonly provider: Provider;
  /** Sign somebody in, or pass null to sign out. */
  setUser(user: SignedInUser | null): void;
  readonly signOut: () => void;
}

export function fakeAuth(
  initial: SignedInUser | null = { email: 'owner@example.invalid' },
  configured = true,
): FakeAuth {
  const user = signal<SignedInUser | null>(initial);
  const signOut = () => user.set(null);
  return {
    provider: {
      provide: AUTH_CONTEXT,
      useValue: {
        user,
        configured,
        token: () => (user() ? 'a-token' : null),
        signIn: async () => {},
        signOut,
      },
    },
    setUser: (next) => user.set(next),
    signOut,
  };
}
