import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { beforeEach, describe, expect, it } from 'vitest';

import { API_BASE_URL } from '../api/api-config';
import { AUTH_CONTEXT, AuthContext } from '../ports/auth-context.port';
import { Membership } from './membership';
import { attachBearerToken } from './auth-interceptor';

const BASE = 'https://desktop.example.invalid';

function setup(token: string | null) {
  const auth: AuthContext = {
    user: signal(null),
    configured: true,
    token: () => token,
    signIn: () => Promise.resolve(),
    signOut: () => undefined,
  };
  TestBed.configureTestingModule({
    providers: [
      provideHttpClient(withInterceptors([attachBearerToken])),
      provideHttpClientTesting(),
      { provide: API_BASE_URL, useValue: BASE },
      { provide: AUTH_CONTEXT, useValue: auth },
    ],
  });
  return {
    http: TestBed.inject(HttpClient),
    controller: TestBed.inject(HttpTestingController),
  };
}

describe('carrying the token', () => {
  let http: HttpClient;
  let controller: HttpTestingController;

  beforeEach(() => ({ http, controller } = setup('a-token')));

  it('attaches it to the edge', () => {
    http.get(`${BASE}/jobs`).subscribe();

    expect(controller.expectOne(`${BASE}/jobs`).request.headers.get('Authorization'))
      .toBe('Bearer a-token');
  });

  it('never attaches it to anything else', () => {
    // An interceptor that signed every request would hand somebody's Google
    // identity to whatever host a later feature happens to call. That kind of
    // leak never shows up in testing, because it works perfectly.
    http.get('https://somewhere-else.invalid/track').subscribe();

    expect(
      controller.expectOne('https://somewhere-else.invalid/track')
        .request.headers.has('Authorization'),
    ).toBe(false);
  });

  it('leaves the health check unauthenticated', () => {
    // It is open by design, and it is how a switched-off desktop is told
    // apart from a sign-in problem.
    http.get(`${BASE}/health`).subscribe();

    expect(controller.expectOne(`${BASE}/health`).request.headers.has('Authorization'))
      .toBe(false);
  });
});

describe('when there is no token', () => {
  it('sends the request anyway rather than blocking it', () => {
    // The server decides who may do what. An unauthenticated request comes
    // back 401, which is an answer the app can act on; a request that never
    // left would just hang.
    const { http, controller } = setup(null);

    http.get(`${BASE}/jobs`).subscribe();

    const sent = controller.expectOne(`${BASE}/jobs`);
    expect(sent.request.headers.has('Authorization')).toBe(false);
  });
});

describe('learning whether this account was let in', () => {
  it('takes a refusal as a verdict', () => {
    const { http, controller } = setup('a-token');
    const member = TestBed.inject(Membership);

    http.get(`${BASE}/library`).subscribe({ error: () => undefined });
    controller
      .expectOne(`${BASE}/library`)
      .flush(null, { status: 403, statusText: 'Forbidden' });

    expect(member.refused()).toBe(true);
    controller.verify();
  });

  it('does not read asking for access as being let in', () => {
    // It answers 202 to somebody who is not admitted, on purpose. Counting
    // that as a success marked them admitted the instant they asked, which
    // took away the very screen they were standing on.
    const { http, controller } = setup('a-token');
    const member = TestBed.inject(Membership);
    http.get(`${BASE}/library`).subscribe({ error: () => undefined });
    controller
      .expectOne(`${BASE}/library`)
      .flush(null, { status: 403, statusText: 'Forbidden' });

    http.post(`${BASE}/access-requests`, {}).subscribe();
    controller
      .expectOne(`${BASE}/access-requests`)
      .flush({ waiting: true }, { status: 202, statusText: 'Accepted' });

    expect(member.refused()).toBe(true);
    controller.verify();
  });

  it('does not read the open health route as being let in', () => {
    // It answers everybody, so it says nothing about this account.
    const { http, controller } = setup('a-token');
    const member = TestBed.inject(Membership);

    http.get(`${BASE}/health`).subscribe();
    controller.expectOne(`${BASE}/health`).flush({ status: 'ok' });

    expect(member.standing()).toBe('unknown');
    controller.verify();
  });
});
