import { TestBed } from '@angular/core/testing';
import { Observable, of } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import { LibraryReply } from '../contract/dto';
import { fakeAuth } from '../auth/fake-auth';
import { LIBRARY } from '../ports/library.port';
import { Prime } from './prime';

function setUp(signedIn: boolean) {
  const list = vi.fn((): Observable<LibraryReply> => of({ tracks: [] }));
  const forget = vi.fn();
  const auth = fakeAuth(signedIn ? { email: 'owner@example.invalid' } : null);
  TestBed.configureTestingModule({
    providers: [auth.provider, { provide: LIBRARY, useValue: { list, forget } }],
  });
  return { auth, list, forget, prime: TestBed.inject(Prime) };
}

describe('fetching ahead of the first page', () => {
  it('starts from outside an injection context, which is where the shell calls it', () => {
    // ngOnInit is not one. Without an injector passed in, effect() throws
    // NG0203 and the prefetch never runs, which is invisible from the
    // outside because the pages still fetch for themselves.
    const { prime } = setUp(false);

    expect(() => prime.start()).not.toThrow();
  });

  it('asks for nothing while nobody is signed in', () => {
    const { prime, list } = setUp(false);
    prime.start();
    TestBed.tick();

    expect(list).not.toHaveBeenCalled();
  });

  it('asks as soon as somebody signs in', () => {
    const { prime, list, auth } = setUp(false);
    prime.start();
    TestBed.tick();

    auth.setUser({ email: 'owner@example.invalid' });
    TestBed.tick();

    expect(list).toHaveBeenCalledOnce();
  });

  it('throws away what was held when somebody signs out', () => {
    // The next person at this browser is not necessarily the same person.
    const { prime, forget, auth } = setUp(true);
    prime.start();
    TestBed.tick();

    auth.setUser(null);
    TestBed.tick();

    expect(forget).toHaveBeenCalled();
  });
});
