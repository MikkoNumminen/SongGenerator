import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { Membership } from './membership';

function member(): Membership {
  TestBed.configureTestingModule({});
  return TestBed.inject(Membership);
}

describe('whether this machine has let somebody in', () => {
  it('does not guess before anything has answered', () => {
    // Drawing a navigation on a guess is how somebody ends up clicking four
    // things that all refuse them.
    const it_ = member();

    expect(it_.standing()).toBe('unknown');
    expect(it_.admitted()).toBe(false);
    expect(it_.refused()).toBe(false);
  });

  it('takes a refusal as a verdict about the account', () => {
    const it_ = member();

    it_.saw(403);

    expect(it_.refused()).toBe(true);
  });

  it('takes a success as being in', () => {
    const it_ = member();

    it_.saw(200);

    expect(it_.admitted()).toBe(true);
  });

  it('leaves a stale token alone', () => {
    // 401 is a sign-in problem, not a verdict. Treating it as refusal would
    // offer to request access somebody may already have.
    const it_ = member();

    it_.saw(401);

    expect(it_.standing()).toBe('unknown');
  });

  it('is not moved by the desktop being switched off', () => {
    // Nothing answered, so nothing was decided.
    const it_ = member();
    it_.saw(200);

    it_.saw(0);
    it_.saw(503);

    expect(it_.admitted()).toBe(true);
  });

  it('changes its mind when the answer changes', () => {
    // Access granted while somebody is sitting on the refused screen, or
    // revoked while they are using it.
    const it_ = member();
    it_.saw(403);

    it_.saw(200);

    expect(it_.admitted()).toBe(true);
  });

  it('knows nothing again once nobody is signed in', () => {
    const it_ = member();
    it_.saw(200);

    it_.forget();

    expect(it_.standing()).toBe('unknown');
  });
});
