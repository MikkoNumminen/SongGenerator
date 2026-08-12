import { Component, inject } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { fakeAuth } from './fake-auth';
import { loadWhenSignedIn } from './load-when-signed-in';

@Component({ selector: 'app-probe', template: '' })
class Probe {
  loads = 0;
  constructor() {
    loadWhenSignedIn(() => (this.loads += 1));
  }
}

function mount(auth: ReturnType<typeof fakeAuth>) {
  TestBed.configureTestingModule({
    providers: [auth.provider],
    imports: [Probe],
  });
  const fixture = TestBed.createComponent(Probe);
  fixture.detectChanges();
  return fixture;
}

describe('fetching once there is somebody to fetch for', () => {
  it('does not ask before anybody has signed in', () => {
    // Asking is the 401 that left a "Try again" button on a page nobody had
    // done anything wrong on.
    const fixture = mount(fakeAuth(null));

    expect(fixture.componentInstance.loads).toBe(0);
  });

  it('asks as soon as somebody signs in', () => {
    const auth = fakeAuth(null);
    const fixture = mount(auth);

    auth.setUser({ email: 'owner@example.invalid' });
    fixture.detectChanges();

    expect(fixture.componentInstance.loads).toBe(1);
  });

  it('asks once for a session that is already signed in', () => {
    const fixture = mount(fakeAuth({ email: 'owner@example.invalid' }));
    fixture.detectChanges();

    expect(fixture.componentInstance.loads).toBe(1);
  });

  it('asks again for a different account', () => {
    // Two accounts do not see the same library, so the answer on screen
    // belongs to whoever was signed in when it was fetched.
    const auth = fakeAuth({ email: 'first@example.invalid' });
    const fixture = mount(auth);

    auth.setUser(null);
    fixture.detectChanges();
    auth.setUser({ email: 'second@example.invalid' });
    fixture.detectChanges();

    expect(fixture.componentInstance.loads).toBe(2);
  });

  it('asks once where sign-in is not set up at all', () => {
    // A clone with no client id is a working deployment with nobody to wait
    // for, not a broken one.
    const fixture = mount(fakeAuth(null, false));
    fixture.detectChanges();

    expect(fixture.componentInstance.loads).toBe(1);
  });
});
