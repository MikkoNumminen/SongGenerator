import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import { UserReply, UsersReply } from '../contract/dto';

/**
 * Who may use this service, as something the owner can change.
 *
 * A port rather than a direct call because the rule it edits lives on the
 * edge, not here. Every method can answer 403: the browser knows whether the
 * signed-in address is an administrator only because the edge said so, and it
 * asks again on every request. A panel that decided for itself would be a
 * suggestion, and the edge would still be the thing enforcing it.
 */
export interface Allowlist {
  /** Everyone granted access, and which addresses are administrators. */
  list(): Observable<UsersReply>;

  /** Grant access. Granting an address that already has it is not an error. */
  grant(email: string): Observable<UserReply>;

  /** Revoke access. Returns the list as it stands afterwards. */
  revoke(email: string): Observable<UsersReply>;
}

export const ALLOWLIST = new InjectionToken<Allowlist>('Allowlist');
