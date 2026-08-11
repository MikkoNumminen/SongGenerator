import { DOCUMENT } from '@angular/common';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AUTH_CONTEXT } from '../ports/auth-context.port';
import { IdleSignOut } from './idle-sign-out';

const LIMIT = 30 * 60 * 1000;

function setUp(signedIn = true) {
  const user = signal(signedIn ? { email: 'owner@example.invalid' } : null);
  const signOut = vi.fn(() => user.set(null));
  TestBed.configureTestingModule({
    providers: [
      {
        provide: AUTH_CONTEXT,
        useValue: { user, signOut, token: () => 'token', configured: true },
      },
    ],
  });
  const idle = TestBed.inject(IdleSignOut);
  return { idle, signOut, document: TestBed.inject(DOCUMENT) };
}

describe('signing out an idle session', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('ends a session nobody has touched for the limit', async () => {
    // The case worth closing: a machine left on a signed-in page in a shared
    // room, for a service that spends a GPU on request.
    const { idle, signOut } = setUp();
    idle.start(LIMIT);

    await vi.advanceTimersByTimeAsync(LIMIT + 60_000);

    expect(signOut).toHaveBeenCalledOnce();
  });

  it('leaves a session alone while somebody is there', async () => {
    const { idle, signOut, document } = setUp();
    idle.start(LIMIT);

    // Half an hour of use, in ten minute steps with a keypress between.
    for (let i = 0; i < 3; i += 1) {
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
      document.dispatchEvent(new Event('keydown'));
    }
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000);

    expect(signOut).not.toHaveBeenCalled();
  });

  it('does not count a hidden tab as being away', async () => {
    // A render takes minutes and people go and do something else while the
    // page polls. Ending the session for that would be punishing the wait.
    const { idle, signOut, document } = setUp();
    idle.start(LIMIT);

    await vi.advanceTimersByTimeAsync(20 * 60 * 1000);
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
    document.dispatchEvent(new Event('visibilitychange'));
    await vi.advanceTimersByTimeAsync(20 * 60 * 1000);

    expect(signOut).not.toHaveBeenCalled();
  });

  it('does nothing when nobody is signed in', async () => {
    const { idle, signOut } = setUp(false);
    idle.start(LIMIT);

    await vi.advanceTimersByTimeAsync(LIMIT * 2);

    expect(signOut).not.toHaveBeenCalled();
  });

  it('signs out once, not on every tick afterwards', async () => {
    const { idle, signOut } = setUp();
    idle.start(LIMIT);

    await vi.advanceTimersByTimeAsync(LIMIT * 3);

    expect(signOut).toHaveBeenCalledOnce();
  });

  it('starting twice does not double the watching', async () => {
    const { idle, signOut } = setUp();
    idle.start(LIMIT);
    idle.start(LIMIT);

    await vi.advanceTimersByTimeAsync(LIMIT + 60_000);

    expect(signOut).toHaveBeenCalledOnce();
  });
});
