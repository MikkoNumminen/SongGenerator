import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../core/api/api-config';
import { LibraryReply, TrackReply } from '../../core/contract/dto';
import { LIBRARY, Library } from '../../core/ports/library.port';
import { PlayerPage } from './player-page';

function track(song: string, bank: string, level: string): TrackReply {
  return { song, bank, level, name: `${song}.${level}.mp3`, bytes: 3_000_000 };
}

const TRACKS: TrackReply[] = [
  track('musicHyva', 'nbank', 'conservative'),
  track('musicHyva', 'nbank', 'wild'),
  track('ukkometso', 'curated', 'conservative'),
];

class FakeLibrary implements Library {
  tracks: TrackReply[] = TRACKS;
  asked: string[] = [];
  failListWith: HttpErrorResponse | null = null;
  failAudioWith: HttpErrorResponse | null = null;

  list(): Observable<LibraryReply> {
    return this.failListWith
      ? throwError(() => this.failListWith)
      : of({ tracks: this.tracks });
  }

  audio(song: string, bank: string, name: string): Observable<Blob> {
    if (this.failAudioWith) {
      return throwError(() => this.failAudioWith);
    }
    this.asked.push(`${song}/${bank}/${name}`);
    return of(new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/mpeg' }));
  }
}

function refused(status: number, detail?: string): HttpErrorResponse {
  return new HttpErrorResponse({ status, error: detail ? { detail } : null });
}

async function render(
  library: FakeLibrary,
  baseUrl = 'https://edge.invalid',
): Promise<ComponentFixture<PlayerPage>> {
  TestBed.configureTestingModule({
    imports: [PlayerPage],
    providers: [
      { provide: LIBRARY, useValue: library },
      { provide: API_BASE_URL, useValue: baseUrl },
    ],
  });
  const fixture = TestBed.createComponent(PlayerPage);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

describe('the player', () => {
  let library: FakeLibrary;

  beforeEach(() => {
    library = new FakeLibrary();
    // jsdom has no object URL implementation.
    let n = 0;
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => `blob:fake/${++n}`),
      revokeObjectURL: vi.fn(),
    });
  });

  it('groups the takes under their song', async () => {
    const fixture = await render(library);

    const songs = fixture.componentInstance.songs();
    expect(songs.map((s) => s.song)).toEqual(['musicHyva', 'ukkometso']);
    expect(songs[0]!.tracks.length).toBe(2);
  });

  it('fetches the audio rather than pointing an element at the edge', async () => {
    // An <audio src> cannot carry an Authorization header, so a plain src
    // would 401 on every track. The fetch is what makes it playable at all.
    const fixture = await render(library);

    fixture.componentInstance.play(TRACKS[0]!);
    await fixture.whenStable();

    expect(library.asked).toEqual(['musicHyva/nbank/musicHyva.conservative.mp3']);
    expect(fixture.componentInstance.source()).toBe('blob:fake/1');
  });

  it('revokes the previous object url when another track is played', async () => {
    // Each one pins its Blob in memory until revoked, and a listening session
    // is dozens of tracks.
    const fixture = await render(library);

    fixture.componentInstance.play(TRACKS[0]!);
    await fixture.whenStable();
    fixture.componentInstance.play(TRACKS[1]!);
    await fixture.whenStable();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fake/1');
    expect(fixture.componentInstance.source()).toBe('blob:fake/2');
  });

  it('revokes the last one when the page goes away', async () => {
    const fixture = await render(library);
    fixture.componentInstance.play(TRACKS[0]!);
    await fixture.whenStable();

    fixture.destroy();

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:fake/1');
  });

  it('reports a switched-off desktop as offline, not as an error', async () => {
    library.failListWith = refused(503);

    const fixture = await render(library);

    expect(fixture.componentInstance.state().kind).toBe('offline');
  });

  it('says so when a track will not load, and keeps the list', async () => {
    library.failAudioWith = refused(404, 'no such track');
    const fixture = await render(library);

    fixture.componentInstance.play(TRACKS[0]!);
    await fixture.whenStable();

    expect(fixture.componentInstance.problem()).toContain('no such track');
    expect(fixture.componentInstance.state().kind).toBe('ready');
    expect(fixture.componentInstance.source()).toBeNull();
  });

  it('is empty rather than loading when nothing has been rendered', async () => {
    library.tracks = [];

    const fixture = await render(library);

    expect(fixture.componentInstance.state().kind).toBe('empty');
  });

  it('asks for nothing when the deployment has no backend address', async () => {
    const asked = vi.spyOn(library, 'list');

    const fixture = await render(library, '');

    expect(asked).not.toHaveBeenCalled();
    expect(fixture.componentInstance.state().kind).toBe('empty');
  });
});
