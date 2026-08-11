import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../core/api/api-config';
import { UserReply, UsersReply } from '../../core/contract/dto';
import { ALLOWLIST, Allowlist } from '../../core/ports/allowlist.port';
import { AUTH_CONTEXT } from '../../core/ports/auth-context.port';
import { AdminPage } from './admin-page';

const OWNER = 'owner@example.invalid';
const GUEST = 'friend@example.invalid';

function reply(users: string[] = [GUEST]): UsersReply {
  return {
    users: users.map((email) => ({
      email,
      added_at: '2026-01-01T00:00:00+00:00',
      added_by: OWNER,
      is_admin: email === OWNER,
    })),
    admins: [OWNER],
  };
}

/** Stands in for the edge. Nothing here reaches a network. */
class FakeAllowlist implements Allowlist {
  listed: UsersReply = reply();
  granted: string[] = [];
  revoked: string[] = [];
  failListWith: HttpErrorResponse | null = null;
  failWriteWith: HttpErrorResponse | null = null;

  list(): Observable<UsersReply> {
    return this.failListWith
      ? throwError(() => this.failListWith)
      : of(this.listed);
  }

  grant(email: string): Observable<UserReply> {
    if (this.failWriteWith) {
      return throwError(() => this.failWriteWith);
    }
    this.granted.push(email);
    return of({
      email,
      added_at: 'now',
      added_by: OWNER,
      is_admin: false,
    });
  }

  revoke(email: string): Observable<UsersReply> {
    if (this.failWriteWith) {
      return throwError(() => this.failWriteWith);
    }
    this.revoked.push(email);
    return of(reply([]));
  }
}

function refused(status: number, detail?: string): HttpErrorResponse {
  return new HttpErrorResponse({ status, error: detail ? { detail } : null });
}

async function render(
  allowlist: FakeAllowlist,
  baseUrl = 'https://edge.invalid',
): Promise<ComponentFixture<AdminPage>> {
  TestBed.configureTestingModule({
    imports: [AdminPage],
    providers: [
      { provide: ALLOWLIST, useValue: allowlist },
      { provide: API_BASE_URL, useValue: baseUrl },
      { provide: AUTH_CONTEXT, useValue: { user: () => ({ email: OWNER }) } },
    ],
  });
  const fixture = TestBed.createComponent(AdminPage);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('the allowlist page', () => {
  let allowlist: FakeAllowlist;

  beforeEach(() => (allowlist = new FakeAllowlist()));

  it('shows who has access', async () => {
    const fixture = await render(allowlist);

    expect(fixture.componentInstance.state().kind).toBe('ready');
    expect(fixture.nativeElement.textContent).toContain(GUEST);
  });

  it('lowercases an address before granting it', async () => {
    // Google hands back a lowercased verified address and the edge compares
    // exactly, so a capital letter here would grant access to nobody.
    const fixture = await render(allowlist);
    fixture.componentInstance.typed.set('  Friend@Example.Invalid  ');

    fixture.componentInstance.grant();
    await fixture.whenStable();

    expect(allowlist.granted).toEqual([GUEST]);
  });

  it('re-reads the list after granting rather than guessing at it', async () => {
    const fixture = await render(allowlist);
    const listing = vi.spyOn(allowlist, 'list');
    fixture.componentInstance.typed.set(GUEST);

    fixture.componentInstance.grant();
    await fixture.whenStable();

    expect(listing).toHaveBeenCalled();
    expect(fixture.componentInstance.typed()).toBe('');
  });

  it("repeats the edge's own reason when it refuses", async () => {
    // The edge explains things this page cannot know, such as an address being
    // an administrator set in the machine's configuration. Replacing that with
    // a generic message would throw away the only explanation there is.
    allowlist.failWriteWith = refused(
      409,
      'that address is an administrator, set in this machine\'s own configuration',
    );
    const fixture = await render(allowlist);

    fixture.componentInstance.revoke(OWNER);
    await fixture.whenStable();

    expect(fixture.componentInstance.problem()).toContain('administrator');
  });

  it('says plainly when the caller is not an administrator', async () => {
    allowlist.failListWith = refused(403, 'only an administrator may change the allowlist');

    const fixture = await render(allowlist);

    expect(fixture.componentInstance.state().kind).toBe('error');
  });

  it('reports the machine being off as offline, not as an error', async () => {
    // A desktop that is switched off is the normal case for this service, and
    // showing it as a fault is the failure the whole application is arranged
    // to avoid.
    allowlist.failListWith = refused(0);

    const fixture = await render(allowlist);

    expect(fixture.componentInstance.state().kind).toBe('offline');
  });

  it('asks for nothing when the deployment has no backend address', async () => {
    const asked = vi.spyOn(allowlist, 'list');

    const fixture = await render(allowlist, '');

    expect(asked).not.toHaveBeenCalled();
    expect(fixture.componentInstance.state().kind).toBe('empty');
  });

  it('offers no revoke for an administrator, because the edge would refuse it', async () => {
    allowlist.listed = reply([OWNER, GUEST]);

    const fixture = await render(allowlist);
    const buttons = fixture.nativeElement.querySelectorAll('button.revoke');

    expect(buttons.length).toBe(1);
  });

  it('does not fire a second write while one is in flight', async () => {
    const fixture = await render(allowlist);
    fixture.componentInstance.working.set(true);

    fixture.componentInstance.revoke(GUEST);

    expect(allowlist.revoked).toEqual([]);
  });
});
