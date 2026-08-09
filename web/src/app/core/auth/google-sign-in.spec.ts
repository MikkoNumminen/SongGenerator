import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { GoogleAuth } from './google-auth';
import { GoogleSignIn } from './google-sign-in';

/** A stand-in, so nothing here loads a script from Google. */
class FakeAuth {
  configured = true;
  mounted: HTMLElement | null = null;
  failWith: Error | null = null;

  mountButton(element: HTMLElement): Promise<void> {
    if (this.failWith) {
      return Promise.reject(this.failWith);
    }
    this.mounted = element;
    return Promise.resolve();
  }

  signIn(): Promise<void> {
    return Promise.resolve();
  }
}

async function render(auth: FakeAuth): Promise<ComponentFixture<GoogleSignIn>> {
  TestBed.configureTestingModule({
    imports: [GoogleSignIn],
    providers: [{ provide: GoogleAuth, useValue: auth }],
  });
  const fixture = TestBed.createComponent(GoogleSignIn);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('the sign-in button', () => {
  let auth: FakeAuth;

  beforeEach(() => (auth = new FakeAuth()));

  it("asks Google to draw its button into the component's own element", async () => {
    const fixture = await render(auth);

    expect(auth.mounted).toBe(
      fixture.nativeElement.querySelector('.host') as HTMLElement,
    );
    expect(fixture.componentInstance.state()).toBe('ready');
  });

  it('says so when the button cannot be drawn, rather than showing a gap', async () => {
    // Blocked by an extension, an offline browser, a network that eats
    // requests to Google. Somebody clicking an empty space is the failure this
    // application is arranged to avoid.
    auth.failWith = new Error('script blocked');

    const fixture = await render(auth);

    expect(fixture.componentInstance.state()).toBe('unavailable');
    expect(fixture.nativeElement.textContent).toContain('could not be loaded');
  });

  it('says when the deployment has no client id at all', async () => {
    // A different problem with a different owner: nothing is wrong with the
    // browser, somebody has not finished setting the site up.
    auth.configured = false;

    const fixture = await render(auth);

    expect(fixture.componentInstance.state()).toBe('unconfigured');
    expect(fixture.nativeElement.textContent).toContain('not set up');
  });

  it('does not ask Google for anything when there is no client id', async () => {
    auth.configured = false;

    await render(auth);

    expect(auth.mounted).toBeNull();
  });

  it('offers One Tap as well, and does not fail when it is suppressed', async () => {
    // It is refused far more often than it appears: a cooldown after somebody
    // dismissed it, third-party cookie rules, a browser on FedCM. The button
    // is the way in; this is a shortcut that may not be there.
    const suppressed = vi
      .spyOn(auth, 'signIn')
      .mockRejectedValue(new Error('suppressed'));

    const fixture = await render(auth);

    expect(suppressed).toHaveBeenCalled();
    expect(fixture.componentInstance.state()).toBe('ready');
  });
});
