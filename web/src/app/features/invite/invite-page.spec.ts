import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../core/api/api-config';
import { AcceptedReply } from '../../core/contract/dto';
import { fakeAuth } from '../../core/auth/fake-auth';
import { INVITATIONS, Invitations } from '../../core/ports/invitations.port';
import { InvitePage } from './invite-page';

const TOKEN = 'a-link';

class FakeInvitations implements Invitations {
  asked: string[] = [];
  failWith: HttpErrorResponse | null = null;

  accept(token: string): Observable<AcceptedReply> {
    this.asked.push(token);
    return this.failWith
      ? throwError(() => this.failWith)
      : of({ email: 'newcomer@example.invalid', banks: ['demo'] });
  }
}

async function render(
  invitations: FakeInvitations,
  auth = fakeAuth(null),
  token: string | null = TOKEN,
): Promise<ComponentFixture<InvitePage>> {
  TestBed.configureTestingModule({
    imports: [InvitePage],
    providers: [
      provideRouter([]),
      auth.provider,
      { provide: INVITATIONS, useValue: invitations },
      { provide: API_BASE_URL, useValue: 'https://edge.invalid' },
      {
        provide: ActivatedRoute,
        useValue: { snapshot: { paramMap: { get: () => token } } },
      },
    ],
  });
  const fixture = TestBed.createComponent(InvitePage);
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
}

describe('opening an invitation link', () => {
  it('asks for nothing until somebody signs in', async () => {
    // The person arriving has no account here and may never have heard of
    // this. Redeeming before they agree would be deciding for them.
    const invitations = new FakeInvitations();

    const fixture = await render(invitations);

    expect(invitations.asked).toEqual([]);
    expect(fixture.componentInstance.step()).toBe('waiting');
  });

  it('redeems by itself once there is an identity', async () => {
    // By then they have agreed twice: opening the link and signing in.
    const invitations = new FakeInvitations();
    const auth = fakeAuth(null);
    const fixture = await render(invitations, auth);

    auth.setUser({ email: 'newcomer@example.invalid' });
    fixture.detectChanges();
    await fixture.whenStable();

    expect(invitations.asked).toEqual([TOKEN]);
    expect(fixture.componentInstance.step()).toBe('joined');
  });

  it('never sends an address of its own', async () => {
    // The edge admits the address Google verified. Anything typed or held
    // here would be a way to redeem a link on somebody else's behalf.
    const invitations = new FakeInvitations();
    const auth = fakeAuth({ email: 'newcomer@example.invalid' });

    await render(invitations, auth);

    expect(invitations.asked).toEqual([TOKEN]);
  });

  it('says a spent link is spent, rather than showing an error code', async () => {
    const invitations = new FakeInvitations();
    invitations.failWith = new HttpErrorResponse({ status: 404 });
    const auth = fakeAuth({ email: 'newcomer@example.invalid' });

    const fixture = await render(invitations, auth);

    expect(fixture.componentInstance.step()).toBe('refused');
    expect(fixture.componentInstance.problem()).toContain('already been used');
  });

  it('tells a sleeping desktop apart from a bad link', async () => {
    // The link is fine; the machine is off. Those need different wording.
    const invitations = new FakeInvitations();
    invitations.failWith = new HttpErrorResponse({ status: 0 });
    const auth = fakeAuth({ email: 'newcomer@example.invalid' });

    const fixture = await render(invitations, auth);

    expect(fixture.componentInstance.step()).toBe('unreachable');
  });

  it('refuses a link with no token in it', async () => {
    const invitations = new FakeInvitations();
    const auth = fakeAuth({ email: 'newcomer@example.invalid' });

    const fixture = await render(invitations, auth, null);

    expect(invitations.asked).toEqual([]);
    expect(fixture.componentInstance.step()).toBe('refused');
  });

  it('redeems once, not on every change detection', async () => {
    const invitations = new FakeInvitations();
    const auth = fakeAuth({ email: 'newcomer@example.invalid' });
    const fixture = await render(invitations, auth);

    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(invitations.asked).toEqual([TOKEN]);
  });
});
