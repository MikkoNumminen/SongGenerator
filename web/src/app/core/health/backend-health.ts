import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, catchError, map, of, tap } from 'rxjs';

import { API_BASE_URL } from '../api/api-config';
import { stateForFailure } from '../api/http-failure';
import { HealthReply } from '../contract/dto';
import { AsyncState, idle, loading, ready, valueOf } from '../state/async-state';

/**
 * Whether the machine that does the work is switched on.
 *
 * This is the first thing the app asks and the answer everything else hangs
 * off, so it is a service with a signal rather than a call each feature makes
 * for itself.
 *
 * `/health` is the one route the edge leaves open, and that is what makes this
 * work: asking "are you there" must not require a token, or a switched-off
 * desktop would be indistinguishable from a sign-in problem and the app would
 * tell somebody to log in again at a machine that cannot answer either way.
 *
 * Nothing here retries on a timer. A poll belongs to whatever is waiting for
 * something, and a background poll from the shell would keep a laptop's radio
 * awake all day to learn something nobody is currently looking at.
 */
@Injectable({ providedIn: 'root' })
export class BackendHealth {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  private readonly state = signal<AsyncState<HealthReply>>(idle());

  /** The raw state, for a view that renders all six cases. */
  readonly status = this.state.asReadonly();

  /** Answered at least once, and answered. */
  readonly reachable = computed(() => this.state().kind === 'ready');

  /**
   * Whether anybody could sign in even in principle.
   *
   * An edge started without an allowlist or a client id is misconfigured
   * rather than unauthorised, and the difference matters: showing a sign-in
   * button that cannot work sends somebody to check their Google account for
   * a problem that is in an environment variable on somebody else's desktop.
   */
  readonly authConfigured = computed(
    () => valueOf(this.state())?.auth_configured ?? false,
  );

  /**
   * Whether a run is already going. The machine takes one at a time, so this
   * is the difference between a disabled button with a reason and a submit
   * that comes back 409.
   */
  readonly busy = computed(() => valueOf(this.state())?.busy ?? false);

  /**
   * Ask once. Safe to call again; the state simply updates.
   *
   * Returns the state rather than nothing so a caller that needs to wait for
   * the answer can, without reaching into the signal and polling it.
   */
  check(): Observable<AsyncState<HealthReply>> {
    this.state.set(loading());
    return this.http.get<HealthReply>(`${this.baseUrl}/health`).pipe(
      // `ready` even when the reply says auth is unconfigured or a run is
      // going: both are answers from a machine that is plainly awake, and
      // that is the only question this service is asking.
      map((reply) => ready(reply)),
      catchError((error: HttpErrorResponse) => of(stateForFailure(error))),
      // Set from the one place the state is decided, so the signal and what a
      // subscriber sees cannot disagree.
      tap((state) => this.state.set(state)),
    );
  }
}
