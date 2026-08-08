import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';

import { API_BASE_URL } from '../api/api-config';
import { HealthReply } from '../contract/dto';
import { BackendHealth } from './backend-health';

const BASE = 'http://desktop.invalid:8000';

describe('BackendHealth', () => {
  let health: BackendHealth;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: API_BASE_URL, useValue: BASE },
      ],
    });
    health = TestBed.inject(BackendHealth);
    http = TestBed.inject(HttpTestingController);
  });

  const answer = (body: HealthReply) => {
    health.check().subscribe();
    http.expectOne(`${BASE}/health`).flush(body);
  };

  it('starts idle, so nothing spins before anything was asked', () => {
    expect(health.status().kind).toBe('idle');
  });

  it('reports the machine as reachable when it answers', () => {
    answer({ status: 'ok', auth_configured: true, busy: false });

    expect(health.reachable()).toBe(true);
    expect(health.authConfigured()).toBe(true);
    expect(health.busy()).toBe(false);
  });

  it('asks without a token, because a switched-off desktop is not a sign-in problem', () => {
    health.check().subscribe();

    const request = http.expectOne(`${BASE}/health`);

    expect(request.request.headers.has('Authorization')).toBe(false);
    request.flush({ status: 'ok', auth_configured: true, busy: false });
  });

  it('is offline, not broken, when nothing answers', () => {
    health.check().subscribe();
    http.expectOne(`${BASE}/health`).error(new ProgressEvent('failed'), { status: 0 });

    expect(health.status().kind).toBe('offline');
    expect(health.reachable()).toBe(false);
  });

  it('is offline when the tunnel is up and the machine behind it is not', () => {
    health.check().subscribe();
    http.expectOne(`${BASE}/health`).flush('no backend', { status: 503, statusText: 'Unavailable' });

    expect(health.status().kind).toBe('offline');
  });

  it('still counts as reachable when nobody could sign in', () => {
    // A misconfigured allowlist is an answer from a machine that is plainly
    // awake. Showing it as offline would send somebody to check the wrong end.
    answer({ status: 'ok', auth_configured: false, busy: false });

    expect(health.reachable()).toBe(true);
    expect(health.authConfigured()).toBe(false);
  });

  it('reports a busy machine so a submit button can say why it is disabled', () => {
    answer({ status: 'ok', auth_configured: true, busy: true });

    expect(health.busy()).toBe(true);
  });

  it('claims nothing about auth or busyness while unreachable', () => {
    // These default to false rather than to the last known answer: a stale
    // "not busy" invites a submit that cannot go anywhere.
    health.check().subscribe();
    http.expectOne(`${BASE}/health`).error(new ProgressEvent('failed'), { status: 0 });

    expect(health.authConfigured()).toBe(false);
    expect(health.busy()).toBe(false);
  });

  it('recovers when the machine comes back', () => {
    health.check().subscribe();
    http.expectOne(`${BASE}/health`).error(new ProgressEvent('failed'), { status: 0 });
    expect(health.status().kind).toBe('offline');

    answer({ status: 'ok', auth_configured: true, busy: false });

    expect(health.reachable()).toBe(true);
  });

  it('hands the verdict to the subscriber as well as the signal', () => {
    // So a caller can wait for the answer instead of polling the signal.
    let seen: string | undefined;
    health.check().subscribe((state) => (seen = state.kind));
    http.expectOne(`${BASE}/health`).flush({ status: 'ok', auth_configured: true, busy: false });

    expect(seen).toBe('ready');
  });
});

describe('BackendHealth: calling check without subscribing', () => {
  it('does not strand the app in loading', () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: API_BASE_URL, useValue: BASE },
      ],
    });
    const health = TestBed.inject(BackendHealth);
    const http = TestBed.inject(HttpTestingController);

    health.check();   // no subscribe: an easy call to write

    http.expectNone(`${BASE}/health`);
    expect(health.status().kind).not.toBe('loading');
  });
});
