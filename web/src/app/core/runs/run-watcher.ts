import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { EMPTY, Observable, catchError, defer, expand, map, of, startWith, switchMap, timer } from 'rxjs';

import { API_BASE_URL } from '../api/api-config';
import { stateForFailure } from '../api/http-failure';
import { JobReply } from '../contract/dto';
import { RUN_SOURCE } from '../ports/run-source.port';
import { AsyncState, failed, loading, ready } from '../state/async-state';

/** How often to ask while a run is going. */
export const POLL_MS = 1_500;

/**
 * How often to ask once it stops answering.
 *
 * Much slower on purpose. A render takes minutes and the machine may have
 * been shut down mid-run, so hammering it every second buys nothing and keeps
 * a laptop's radio awake for an answer nobody is waiting on any more.
 */
export const OFFLINE_POLL_MS = 8_000;

/**
 * Watch one run until it stops changing.
 *
 * Polling rather than a socket, because the edge has no socket and adding one
 * would mean keeping a connection open to a desktop that is expected to go
 * away mid-conversation. Polling degrades into "offline" on its own.
 *
 * The interesting parts are all about not making things worse:
 *
 * - a slow reply never queues another request behind it, because the next
 *   poll is scheduled from the previous answer rather than from a clock
 * - an unreachable machine is asked far less often
 * - the stream ends when the run is settled, so a finished job stops costing
 *   requests forever just because a tab is open on it
 */
@Injectable({ providedIn: 'root' })
export class RunWatcher {
  private readonly runs = inject(RUN_SOURCE);
  private readonly configured = inject(API_BASE_URL) !== '';

  watch(id: string): Observable<AsyncState<JobReply>> {
    // With no address the request would go to `/jobs/<id>` on this site, which
    // a static host answers with index.html, and the poll would keep asking
    // forever for HTML it cannot read.
    if (!this.configured) {
      return of(failed('This site has not been told where its backend is.'));
    }
    return defer(() => this.ask(id)).pipe(
      expand((state) =>
        this.isFinal(state)
          ? EMPTY
          : timer(this.delayAfter(state)).pipe(switchMap(() => this.ask(id))),
      ),
      // So a view has something to render on the first frame rather than a
      // blank panel until the first answer arrives.
      startWith(loading() as AsyncState<JobReply>),
    );
  }

  private ask(id: string): Observable<AsyncState<JobReply>> {
    return this.runs.job(id).pipe(
      map((job) => ready(job)),
      catchError((error: HttpErrorResponse) => of(stateForFailure(error))),
    );
  }

  /**
   * Whether to stop asking.
   *
   * `settled` comes from the edge, which knows the difference between a run
   * that finished and a stage line printed while the process was still
   * exiting. An error stops it too: a run id that does not exist will not
   * start existing, and retrying a 404 forever is just noise.
   *
   * `offline` deliberately does NOT stop it. That is the case where waiting
   * is exactly the right thing to do, because the desktop may well come back.
   */
  private isFinal(state: AsyncState<JobReply>): boolean {
    if (state.kind === 'ready') {
      return state.value.settled;
    }
    return state.kind === 'error';
  }

  private delayAfter(state: AsyncState<JobReply>): number {
    return state.kind === 'offline' ? OFFLINE_POLL_MS : POLL_MS;
  }
}
