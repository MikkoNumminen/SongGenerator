import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { BanksReply } from '../contract/dto';
import { BankCatalog } from '../ports/bank-catalog.port';
import { API_BASE_URL } from './api-config';

/** The live edge, behind the BankCatalog port. */
@Injectable({ providedIn: 'root' })
export class HttpBankCatalog implements BankCatalog {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  list(): Observable<BanksReply> {
    return this.http.get<BanksReply>(`${this.baseUrl}/banks`);
  }
}
