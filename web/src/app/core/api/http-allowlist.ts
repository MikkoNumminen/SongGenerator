import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { UserReply, UsersReply } from '../contract/dto';
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

  grant(email: string): Observable<UserReply> {
    return this.http.post<UserReply>(`${this.baseUrl}/users`, { email });
  }

  revoke(email: string): Observable<UsersReply> {
    // Encoded because an address is a path segment here and contains an @,
    // and because a '+' in a Gmail address is a space to a URL parser.
    return this.http.delete<UsersReply>(
      `${this.baseUrl}/users/${encodeURIComponent(email)}`,
    );
  }
}
