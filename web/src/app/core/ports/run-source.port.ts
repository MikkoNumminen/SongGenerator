import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import {
  FilesReply,
  HistoryReply,
  JobReply,
  SubmitBody,
} from '../contract/dto';

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
  /**
   * Runs this caller may see, optionally narrowed to one address.
   *
   * The address is a convenience for somebody who can already see all of
   * them, never a way to see more: the edge applies it on top of the same
   * check, so naming somebody whose runs are not yours returns nothing.
   */
  history(limit?: number, requestedBy?: string): Observable<HistoryReply>;
  cancel(id: string): Observable<void>;

  /** What a run produced, once it has finished. Empty while it is still going. */
  files(id: string): Observable<FilesReply>;

  /**
   * One of those renderings, as bytes.
   *
   * A Blob rather than a URL for the same reason the library hands one back:
   * an `<audio src>` cannot carry the Authorization header every route needs,
   * and a token in a query string ends up in logs and history.
   */
  file(id: string, name: string): Observable<Blob>;
}

export const RUN_SOURCE = new InjectionToken<RunSource>('RunSource');
