import { HttpErrorResponse } from '@angular/common/http';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { API_BASE_URL } from '../../core/api/api-config';
import { LibraryReply, TrackReply } from '../../core/contract/dto';
import { LIBRARY, Library } from '../../core/ports/library.port';
import { ANY, PlayerPage } from './player-page';

function track(song: string, bank: string, level: string): TrackReply {
  return { song, bank, level, name: `${song}.${level}.mp3`, bytes: 3_000_000 };
}

const TRACKS: TrackReply[] = [
  track('musicHyva', 'nbank', 'conservative'),
  track('musicHyva', 'nbank', 'wild'),
  track('ukkometso', 'ppbank', 'conservative'),
];

class FakeLibrary implements Library {
  tracks: TrackReply[];
  asked: string[] = [];
  failListWith: HttpErrorResponse | null = null;
  failAudioWith: HttpErrorResponse | null = null;

  constructor(tracks: TrackReply[] = TRACKS) {
    this.tracks = tracks;
  }

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
  let created: ReturnType<typeof vi.fn>;
  let revoked: ReturnType<typeof vi.fn>;
  let original: {
    create: typeof URL.createObjectURL;
    revoke: typeof URL.revokeObjectURL;
  };

  beforeEach(() => {
    library = new FakeLibrary();
    // jsdom implements neither of these, so they are added to the real URL
    // rather than replacing it.
    //
    // Replacing it is what the first version did, with vi.stubGlobal and a
    // spread of the class. Spreading a constructor copies none of its call
    // behaviour, so `new URL(...)` stopped working everywhere, and because a
    // stubbed global outlives the file that set it, seven unrelated suites
    // failed with "URL is not a constructor". Every one of them passed here
    // and failed in CI, which is the shape of bug worth a comment.
    let n = 0;
    created = vi.fn(() => `blob:fake/${++n}`);
    revoked = vi.fn();
    original = {
      create: URL.createObjectURL,
      revoke: URL.revokeObjectURL,
    };
    URL.createObjectURL = created as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL = revoked as unknown as typeof URL.revokeObjectURL;
  });

  afterEach(() => {
    URL.createObjectURL = original.create;
    URL.revokeObjectURL = original.revoke;
  });

  it('leaves the URL constructor alone', () => {
    // The guard for the bug this file caused. Replacing the global with a
    // spread of the class took `new URL(...)` away from every other suite,
    // and a stubbed global outlives the file that set it. Seven suites failed
    // in CI while this one passed locally, so the invariant is asserted here
    // rather than trusted.
    expect(new URL('https://example.invalid/a').pathname).toBe('/a');
    // And that the two helpers really were installed on it, rather than the
    // assertion above passing because nothing was stubbed at all.
    expect(URL.createObjectURL).toBe(created);
  });

  it('choosing a take does not play it', async () => {
    // The point of the redesign. Somebody looking through a list on a shared
    // machine must not make the room hear it; playing is a second, deliberate
    // press.
    const fixture = await render(library);

    fixture.componentInstance.select(TRACKS[0]!);
    await fixture.whenStable();

    expect(library.asked).toEqual([]);
    expect(fixture.componentInstance.source()).toBeNull();
    expect(fixture.componentInstance.isSelected(TRACKS[0]!)).toBe(true);
  });

  it('choosing the same take again closes it', async () => {
    const fixture = await render(library);
    fixture.componentInstance.select(TRACKS[0]!);

    fixture.componentInstance.select(TRACKS[0]!);

    expect(fixture.componentInstance.isSelected(TRACKS[0]!)).toBe(false);
  });

  it('shuffles only what the two choices allow', async () => {
    // The library holds a conservative and a wild reading of nearly
    // everything, so shuffling all of it would play each song twice in a row.
    const fixture = await render(library);
    fixture.componentInstance.bank.set('nbank');
    fixture.componentInstance.level.set('wild');

    expect(fixture.componentInstance.matching().map((t) => t.name)).toEqual([
      'musicHyva.wild.mp3',
    ]);

    fixture.componentInstance.shuffle();
    await fixture.whenStable();

    expect(library.asked).toEqual(['musicHyva/nbank/musicHyva.wild.mp3']);
  });

  it('shuffle plays on to the next when one finishes', async () => {
    const fixture = await render(library);
    fixture.componentInstance.shuffle();
    await fixture.whenStable();
    const first = library.asked.length;

    fixture.componentInstance.next();
    await fixture.whenStable();

    expect(library.asked.length).toBe(first + 1);
  });

  it('one chosen take does not run on to the next when it ends', async () => {
    const fixture = await render(library);
    fixture.componentInstance.play(TRACKS[0]!);
    await fixture.whenStable();
    const played = library.asked.length;

    fixture.componentInstance.next();
    await fixture.whenStable();

    expect(library.asked.length).toBe(played);
  });

  it('downloading does not start the music', async () => {
    // Saving has to fetch the same bytes, because an anchor cannot carry the
    // Authorization header. It must not look like playing to the room.
    const fixture = await render(library);
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    fixture.componentInstance.save(TRACKS[0]!);
    await fixture.whenStable();

    expect(library.asked.length).toBe(1);
    expect(fixture.componentInstance.source()).toBeNull();
  });

  it('does not restart the shuffle when what ended is not in the queue', async () => {
    const fixture = await render(library);
    fixture.componentInstance.shuffle();
    await fixture.whenStable();
    const played = library.asked.length;
    // A selection the queue does not contain. findIndex returns -1, and
    // queue[at + 1] would be queue[0].
    fixture.componentInstance.selected.set(
      track('somewhere else', 'nbank', 'wild'),
    );

    fixture.componentInstance.next();
    await fixture.whenStable();

    expect(library.asked.length).toBe(played);
  });

  it('groups the takes under their song', async () => {
    const fixture = await render(library);

    const songs = fixture.componentInstance.songs();
    expect(songs.map((s) => s.song)).toEqual(['musicHyva', 'ukkometso']);
    expect(songs[0]!.takes.length).toBe(2);
  });

  it('calls itself the demo when that is all there is', async () => {
    // Somebody holding the demo library alone is not looking at everything
    // made so far, and a heading saying so describes a machine they cannot
    // see.
    const onlyDemo = new FakeLibrary([
      track('a_demo_song', 'demo', 'wild'),
      track('another_demo_song', 'demo', 'conservative'),
    ]);

    const fixture = await render(onlyDemo);

    expect(fixture.componentInstance.title()).toBe('SongGenerator demo');
  });

  it('calls itself everything made so far when there is more than the demo',
    async () => {
      const fixture = await render(library);

      expect(fixture.componentInstance.title()).toBe('Everything made so far');
    });

  it('carries a readable title beside the folder name', async () => {
    // The folder name has to stay reachable, because that is what the machine
    // calls it, but it is not what a list of thirty is read by.
    const fixture = await render(library);

    const songs = fixture.componentInstance.songs();
    expect(songs.map((s) => s.title)).toEqual(['Music Hyva', 'Ukkometso']);
    expect(songs.map((s) => s.song)).toEqual(['musicHyva', 'ukkometso']);
  });

  it('says on the button how much it would play', async () => {
    // The number is the button's, so it has to be part of what the button is
    // called rather than a decoration beside the word.
    const fixture = await render(library);
    const button: HTMLButtonElement =
      fixture.nativeElement.querySelector('.shuffle__go');
    const everything = fixture.componentInstance.matching().length;

    expect(button.getAttribute('aria-label')).toBe(`Shuffle ${everything} takes`);

    fixture.componentInstance.chooseLevel('wild');
    fixture.detectChanges();

    const fewer = fixture.componentInstance.matching().length;
    expect(fewer).toBeLessThan(everything);
    expect(button.getAttribute('aria-label')).toBe(`Shuffle ${fewer} takes`);
  });

  it('narrows the shuffle from the control itself', async () => {
    // Driven through the DOM rather than by calling the method, because the
    // binding between the two is the part that can come undone.
    const fixture = await render(library);
    const everything = fixture.componentInstance.matching().length;

    const radios: HTMLInputElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('input[name="level"]'),
    );
    const wild = radios.find(
      (r) => r.closest('label')?.getAttribute('data-level') === 'wild',
    );
    expect(wild).toBeTruthy();

    wild!.click();
    fixture.detectChanges();

    expect(fixture.componentInstance.level()).toBe('wild');
    expect(fixture.componentInstance.matching().length).toBeLessThan(everything);
  });

  it('narrows the shuffle by bank and by level', async () => {
    const fixture = await render(library);
    const page = fixture.componentInstance;
    const everything = page.matching().length;

    page.chooseLevel('wild');
    fixture.detectChanges();

    expect(page.matching().length).toBeLessThan(everything);
    expect(page.matching().every((t) => t.level === 'wild')).toBe(true);

    page.chooseLevel(ANY);
    fixture.detectChanges();
    expect(page.matching().length).toBe(everything);
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

    expect(revoked).toHaveBeenCalledWith('blob:fake/1');
    expect(fixture.componentInstance.source()).toBe('blob:fake/2');
  });

  it('revokes the last one when the page goes away', async () => {
    const fixture = await render(library);
    fixture.componentInstance.play(TRACKS[0]!);
    await fixture.whenStable();

    fixture.destroy();

    expect(revoked).toHaveBeenCalledWith('blob:fake/1');
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
