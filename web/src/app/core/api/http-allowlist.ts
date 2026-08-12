import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  InvitationReply,
  InvitationsReply,
  UserReply,
  UsersReply,
} from '../contract/dto';
import { Allowlist } from '../ports/allowlist.port';
import { API_BASE_URL } from './api-config';

/** The live edge, behind the Allowlist port. */
@Injectable({ providedIn: 'root' })
export class HttpAllowlist implements Allowlist {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  list(): Observable<UsersReply> {
    return this.http.get<UsersReply>(`${this.baseUrl}/users`);
  }

  grant(email: string, banks?: readonly string[]): Observable<UserReply> {
    // Omitted rather than sent empty: the edge reads "no banks field" as its
    // own default, and an empty array as somebody clearing every box.
    const body = banks ? { email, banks: [...banks] } : { email };
    return this.http.post<UserReply>(`${this.baseUrl}/users`, body);
  }

  setBanks(email: string, banks: readonly string[]): Observable<UsersReply> {
    return this.http.put<UsersReply>(
      `${this.baseUrl}/users/${encodeURIComponent(email)}/banks`,
      { banks: [...banks] },
    );
  }

  setSeesAllRuns(email: string, seeAll: boolean): Observable<UsersReply> {
    return this.http.put<UsersReply>(
      `${this.baseUrl}/users/${encodeURIComponent(email)}/runs`,
      { see_all_runs: seeAll },
    );
  }

  invitations(): Observable<InvitationsReply> {
    return this.http.get<InvitationsReply>(`${this.baseUrl}/invitations`);
  }

  invite(): Observable<InvitationReply> {
    return this.http.post<InvitationReply>(`${this.baseUrl}/invitations`, {});
  }

  withdraw(token: string): Observable<InvitationsReply> {
    return this.http.delete<InvitationsReply>(
      `${this.baseUrl}/invitations/${encodeURIComponent(token)}`,
    );
  }

  revoke(email: string): Observable<UsersReply> {
    // Encoded because an address is a path segment here and contains an @,
    // and because a '+' in a Gmail address is a space to a URL parser.
    return this.http.delete<UsersReply>(
      `${this.baseUrl}/users/${encodeURIComponent(email)}`,
    );
  }
}
