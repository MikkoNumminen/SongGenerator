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
  /**
   * Everything rendered, fetched once a session.
   *
   * Held afterwards, so moving between pages does not re-ask for a library
   * that has not changed. Whoever asks first starts the request; whoever
   * arrives later joins it or is answered from what is already in hand.
   */
  list(): Observable<LibraryReply>;

  audio(song: string, bank: string, name: string): Observable<Blob>;

  /**
   * Throw away what is held, so the next ask fetches again.
   *
   * Called when a render finishes and when somebody signs out. Both are
   * moments this application already knows about, which is why nothing here
   * expires on a timer: an age would be a guess about the same two events.
   */
  forget(): void;
}

export const LIBRARY = new InjectionToken<Library>('Library');
