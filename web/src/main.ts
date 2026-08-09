import { bootstrapApplication } from '@angular/platform-browser';

import { App } from './app/app';
import { appConfigWith } from './app/app.config';
import { loadRuntimeConfig } from './app/core/config/runtime-config';

/**
 * Read the deployment's settings, then start.
 *
 * The wait is one small file and it happens once. Doing it before bootstrap
 * rather than after means no component ever sees a half-configured
 * application, and nothing has to re-read an address that changed underneath
 * it while a request was in flight.
 *
 * `loadRuntimeConfig` never rejects, so a missing or broken config file still
 * produces a running application. It falls back to the local backend, which
 * shows up as "that machine is not answering": a state this application knows
 * how to render, rather than a blank page.
 */
loadRuntimeConfig()
  .then((config) => bootstrapApplication(App, appConfigWith(config)))
  .catch((err) => console.error(err));
