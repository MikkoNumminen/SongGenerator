import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import { AcceptedReply } from '../contract/dto';

/**
 * Redeeming an invitation, from the side of the person being invited.
 *
 * A port of its own rather than a method on the allowlist, because the two are
 * used by opposite people: the allowlist is the owner deciding who may come in,
 * and this is a stranger arriving with a link. Nothing here can grant anything.
 * It carries a link to the edge, which decides.
 */
export interface Invitations {
  /**
   * Spend a link.
   *
   * The address admitted comes from the Google token the interceptor attaches,
   * never from anything passed here, so a link cannot be redeemed on somebody
   * else's behalf.
   */
  accept(token: string): Observable<AcceptedReply>;
}

export const INVITATIONS = new InjectionToken<Invitations>('Invitations');
