import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { LibraryReply } from '../contract/dto';
import { Kept } from '../data/kept';
import { Library } from '../ports/library.port';
import { API_BASE_URL } from './api-config';

/** The live edge, behind the Library port. */
@Injectable({ providedIn: 'root' })
export class HttpLibrary implements Library {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = inject(API_BASE_URL);

  /** Fetched once a session. A render finishing is what makes it stale. */
  private readonly kept = new Kept<LibraryReply>(() =>
    this.http.get<LibraryReply>(`${this.baseUrl}/library`));

  list(): Observable<LibraryReply> {
    return this.kept.get();
  }

  /** Whether a caller can draw immediately instead of showing a wait. */
  get ready(): boolean {
    return this.kept.ready;
  }

  forget(): void {
    this.kept.forget();
  }

  audio(song: string, bank: string, name: string): Observable<Blob> {
    // Each segment encoded on its own. Song folders carry spaces, brackets and
    // Finnish vowels, and one of them is called `music_sdp`; encoding the
    // joined string would escape the separators along with them.
    const path = [song, bank, name].map(encodeURIComponent).join('/');
    return this.http.get(`${this.baseUrl}/library/${path}`, {
      responseType: 'blob',
    });
  }
}
