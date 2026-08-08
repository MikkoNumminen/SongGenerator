import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import { HistoryReply, JobReply, SubmitBody } from '../contract/dto';

/**
 * Runs: starting one, watching it, and what happened before.
 *
 * This is the port with two implementations in mind. Today it is the live
 * edge. Later it is a second class reading static files, so the site is worth
 * opening while the desktop is off, and choosing between them is one provider
 * swap at bootstrap with no component learning which it got.
 *
 * That is also what makes "the backend is down" testable without mocking HTTP
 * or running Python: provide a different `RunSource`.
 *
 * Cancel returns nothing useful, so it returns void. The caller learns the
 * outcome by watching the run, which is where the truth already is.
 */
export interface RunSource {
  submit(request: SubmitBody): Observable<JobReply>;
  job(id: string): Observable<JobReply>;
  history(limit?: number): Observable<HistoryReply>;
  cancel(id: string): Observable<void>;
}

export const RUN_SOURCE = new InjectionToken<RunSource>('RunSource');
