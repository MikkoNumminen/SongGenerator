import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  FilesReply,
  HistoryReply,
  JobReply,
  SubmitBody,
} from '../contract/dto';
import { RunSource } from '../ports/run-source.port';
import { API_BASE_URL } from './api-config';

/**
 * The live edge, behind the RunSource port.
 *
 * Deliberately dull: one method per route, no retries, no caching, no
 * interpretation. Anything cleverer belongs above this, where a feature can
 * decide what a failure means in its own context, and anything about the run
 * itself belongs in the pipeline, which is the only thing that knows.
 *
 * Failures are left to propagate as HttpErrorResponse. Turning them into
 * states here would mean every caller got the same wording for a failure whose
 * meaning depends entirely on what was being attempted.
 */
@Injectable({ providedIn: 'root' })
export class HttpRunSource implements RunSource {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  submit(request: SubmitBody): Observable<JobReply> {
    return this.http.post<JobReply>(`${this.baseUrl}/jobs`, request);
  }

  job(id: string): Observable<JobReply> {
    return this.http.get<JobReply>(
      `${this.baseUrl}/jobs/${encodeURIComponent(id)}`,
    );
  }

  history(limit?: number, requestedBy?: string): Observable<HistoryReply> {
    // The edge caps this itself, so nothing here needs to guess a maximum.
    let params = new HttpParams();
    if (limit !== undefined) {
      params = params.set('limit', limit);
    }
    if (requestedBy) {
      params = params.set('requested_by', requestedBy);
    }
    return this.http.get<HistoryReply>(`${this.baseUrl}/jobs`, {
      params: params.keys().length ? params : undefined,
    });
  }

  files(id: string): Observable<FilesReply> {
    return this.http.get<FilesReply>(
      `${this.baseUrl}/jobs/${encodeURIComponent(id)}/files`);
  }

  file(id: string, name: string): Observable<Blob> {
    return this.http.get(
      `${this.baseUrl}/jobs/${encodeURIComponent(id)}/files/${encodeURIComponent(name)}`,
      { responseType: 'blob' });
  }

  cancel(id: string): Observable<void> {
    return this.http.post<void>(
      `${this.baseUrl}/jobs/${encodeURIComponent(id)}/cancel`,
      {},
    );
  }
}
