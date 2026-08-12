import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { AcceptedReply } from '../contract/dto';
import { Invitations } from '../ports/invitations.port';
import { API_BASE_URL } from './api-config';

/** The live edge, behind the Invitations port. */
@Injectable({ providedIn: 'root' })
export class HttpInvitations implements Invitations {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  accept(token: string): Observable<AcceptedReply> {
    return this.http.post<AcceptedReply>(
      `${this.baseUrl}/invitations/${encodeURIComponent(token)}/accept`,
      {},
    );
  }
}
