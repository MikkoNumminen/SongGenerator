import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AccessRequestsReply,
  AskedReply,
  UsersReply,
} from '../contract/dto';
import { AccessRequests } from '../ports/access-requests.port';
import { API_BASE_URL } from './api-config';

/** The live edge, behind the AccessRequests port. */
@Injectable({ providedIn: 'root' })
export class HttpAccessRequests implements AccessRequests {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  ask(): Observable<AskedReply> {
    return this.http.post<AskedReply>(`${this.baseUrl}/access-requests`, {});
  }

  waiting(): Observable<AccessRequestsReply> {
    return this.http.get<AccessRequestsReply>(`${this.baseUrl}/access-requests`);
  }

  approve(email: string): Observable<UsersReply> {
    return this.http.post<UsersReply>(
      `${this.baseUrl}/access-requests/${encodeURIComponent(email)}/approve`,
      {},
    );
  }

  dismiss(email: string): Observable<AccessRequestsReply> {
    return this.http.delete<AccessRequestsReply>(
      `${this.baseUrl}/access-requests/${encodeURIComponent(email)}`,
    );
  }
}
