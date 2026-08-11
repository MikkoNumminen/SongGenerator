import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

import { LibraryReply } from '../contract/dto';

/**
 * Everything this machine has already rendered, and the audio itself.
 *
 * `audio` returns a Blob rather than a URL because an `<audio src>` cannot
 * carry an Authorization header, and every route but the health check needs
 * one. The alternatives were a token in the query string, which ends up in
 * logs, history and anything pasted, or this: fetch it as data and hand the
 * element an object URL. A rendering is a few megabytes, so holding one in
 * memory to play it costs nothing worth counting.
 */
export interface Library {
  list(): Observable<LibraryReply>;

  audio(song: string, bank: string, name: string): Observable<Blob>;
}

export const LIBRARY = new InjectionToken<Library>('Library');
