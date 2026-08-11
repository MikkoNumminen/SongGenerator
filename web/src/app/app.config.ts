import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';

import { API_BASE_URL } from './core/api/api-config';
import { HttpAllowlist } from './core/api/http-allowlist';
import { HttpBankCatalog } from './core/api/http-bank-catalog';
import { HttpLibrary } from './core/api/http-library';
import { HttpRunSource } from './core/api/http-run-source';
import { retryTheHop } from './core/api/retry-the-hop';
import { attachBearerToken } from './core/auth/auth-interceptor';
import { RuntimeConfig } from './core/config/runtime-config';
import { GOOGLE_CLIENT_ID, GoogleAuth } from './core/auth/google-auth';
import { AUTH_CONTEXT } from './core/ports/auth-context.port';
import { ALLOWLIST } from './core/ports/allowlist.port';
import { BANK_CATALOG } from './core/ports/bank-catalog.port';
import { LIBRARY } from './core/ports/library.port';
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
 * API_BASE_URL and GOOGLE_CLIENT_ID come from the runtime config rather than
 * from this file, because both differ per deployment and neither is worth a
 * rebuild. See core/config/runtime-config.
 */
export function appConfigWith(config: RuntimeConfig): ApplicationConfig {
  return {
  providers: [
    { provide: API_BASE_URL, useValue: config.apiBaseUrl },
    { provide: GOOGLE_CLIENT_ID, useValue: config.googleClientId },
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    // Retry first, so it wraps the token attachment rather than sitting
    // inside it: each attempt then runs attachBearerToken again and asks for
    // the token as it stands, instead of replaying whatever was attached to
    // the attempt that failed.
    provideHttpClient(withInterceptors([retryTheHop, attachBearerToken])),
    { provide: ALLOWLIST, useExisting: HttpAllowlist },
    { provide: BANK_CATALOG, useExisting: HttpBankCatalog },
    { provide: LIBRARY, useExisting: HttpLibrary },
    { provide: RUN_SOURCE, useExisting: HttpRunSource },
    { provide: AUTH_CONTEXT, useExisting: GoogleAuth },
  ],
  };
}
