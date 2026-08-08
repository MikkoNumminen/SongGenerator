import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';

import { HttpBankCatalog } from './core/api/http-bank-catalog';
import { HttpRunSource } from './core/api/http-run-source';
import { attachBearerToken } from './core/auth/auth-interceptor';
import { GoogleAuth } from './core/auth/google-auth';
import { AUTH_CONTEXT } from './core/ports/auth-context.port';
import { BANK_CATALOG } from './core/ports/bank-catalog.port';
import { RUN_SOURCE } from './core/ports/run-source.port';
import { routes } from './app.routes';

/**
 * Where the ports meet their implementations, and the only place that knows
 * which one anything got.
 *
 * This is the seam the whole shape exists for: pointing RUN_SOURCE at a class
 * that reads static files instead of the edge is a one line change here, and
 * no component learns about it.
 *
 * API_BASE_URL and GOOGLE_CLIENT_ID are deliberately not overridden here. They
 * carry defaults that suit a machine you are sitting at, and a deployment
 * provides its own rather than editing a file that is checked in.
 */
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideHttpClient(withInterceptors([attachBearerToken])),
    { provide: BANK_CATALOG, useExisting: HttpBankCatalog },
    { provide: RUN_SOURCE, useExisting: HttpRunSource },
    { provide: AUTH_CONTEXT, useExisting: GoogleAuth },
  ],
};
