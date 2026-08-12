import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AccessRequestsReply,
  AskedReply,
  UsersReply,
} from '../contract/dto';

/**
 * Asking to be let in, and the queue that answers.
 *
 * Two audiences in one port because they are two ends of one thing: a person
 * refused by this machine asks, and the person who runs it decides. Nothing
 * here grants anything; `ask` puts a name in a queue and `approve` is refused
 * by the edge for anybody but an administrator.
 */
export interface AccessRequests {
  /** Ask. Open to any account Google will vouch for, because the people who
   * need it are by definition not on the list. */
  ask(): Observable<AskedReply>;

  /** Everybody waiting. Administrators only. */
  waiting(): Observable<AccessRequestsReply>;

  /** Let somebody in with the demo library, and clear their request. */
  approve(email: string): Observable<UsersReply>;

  /** Remove a request without admitting anybody. */
  dismiss(email: string): Observable<AccessRequestsReply>;
}

export const ACCESS_REQUESTS = new InjectionToken<AccessRequests>(
  'AccessRequests',
);
