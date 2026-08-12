import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import {
  InvitationReply,
  InvitationsReply,
  UserReply,
  UsersReply,
} from '../contract/dto';

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

  /**
   * Grant access. Granting an address that already has it is not an error.
   *
   * Without banks the edge gives the demo library and nothing else, which is
   * what a newly typed address should get: it is a stranger until somebody
   * says otherwise, and the safe default belongs on the server rather than in
   * whatever this panel last had on screen.
   */
  grant(email: string, banks?: readonly string[]): Observable<UserReply>;

  /** Change which libraries an address may see. Returns the list afterwards. */
  setBanks(email: string, banks: readonly string[]): Observable<UsersReply>;

  /**
   * Whether an address sees every run or only the ones it asked for.
   *
   * Off unless granted. A run names a song somebody chose to make, which is a
   * more personal thing than the list of what exists.
   */
  setSeesAllRuns(email: string, seeAll: boolean): Observable<UsersReply>;

  /** Revoke access. Returns the list as it stands afterwards. */
  revoke(email: string): Observable<UsersReply>;

  /** Outstanding and spent invitations. */
  invitations(): Observable<InvitationsReply>;

  /**
   * Make a link that admits exactly one account, to the demo library.
   *
   * What it grants is not a parameter. A link that could be made to grant
   * more would be a link worth stealing.
   */
  invite(): Observable<InvitationReply>;

  /** Withdraw an unused link. Spent ones are kept as a record. */
  withdraw(token: string): Observable<InvitationsReply>;
}

export const ALLOWLIST = new InjectionToken<Allowlist>('Allowlist');
