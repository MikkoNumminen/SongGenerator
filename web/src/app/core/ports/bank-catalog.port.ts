import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import { BanksReply } from '../contract/dto';

/**
 * Which banks this machine can actually sing with.
 *
 * The names are data, never a union type. Banks live in a gitignored local
 * override, so which ones exist differs per machine and is not knowable when
 * this is built: a `'curated' | 'muslimbank'` type would be wrong on a fresh
 * clone and would need editing every time somebody records a new one.
 *
 * The reply carries whether each bank is usable and why not, so a picker can
 * disable an option and say what is missing rather than offering something
 * that fails the moment somebody presses go.
 */
export interface BankCatalog {
  list(): Observable<BanksReply>;
}

export const BANK_CATALOG = new InjectionToken<BankCatalog>('BankCatalog');
