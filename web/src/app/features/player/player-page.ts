import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { API_BASE_URL } from '../../core/api/api-config';
import {
  detailOf,
  isUnreachable,
  stateForFailure,
} from '../../core/api/http-failure';
import { TrackReply } from '../../core/contract/dto';
import { LIBRARY } from '../../core/ports/library.port';
import {
  AsyncState,
  empty,
  idle,
  loading,
  ready,
  valueOf,
} from '../../core/state/async-state';
import { StatePanel } from '../../shared/state-panel/state-panel';

/** One song, with the takes that exist for it. */
export interface SongGroup {
  readonly song: string;
  readonly takes: readonly TrackReply[];
}

/** Any bank, or a named one. */
export const ANY = '__any__';

function keyOf(track: TrackReply): string {
  return `${track.song}/${track.bank}/${track.name}`;
}

/**
 * Everything already made, listed quietly and played on request.
 *
 * Two decisions shape this page, both about not being clicked at.
 *
 * Choosing a take does not play it. Selecting reveals the controls under that
 * one row and nothing else happens, so a person can look through a list on a
 * shared machine without the room hearing it. Playing is the second, deliberate
 * press.
 *
 * The controls live under the selected row rather than in a bar somewhere
 * else. What is playing is then always next to what was chosen, and there is
 * only ever one of them open, so the page does not accumulate players.
 *
 * Shuffle is the one thing that starts on its own, because asking for it is
 * already the instruction, and it is narrowed by bank and by take: the library
 * holds a conservative and a wild reading of nearly everything, so shuffling
 * all of it would play each song twice in a row.
 */
@Component({
  selector: 'app-player-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [StatePanel],
  templateUrl: './player-page.html',
  styleUrl: './player-page.css',
})
export class PlayerPage implements OnInit, OnDestroy {
  private readonly library = inject(LIBRARY);
  private readonly destroyRef = inject(DestroyRef);
  private readonly configured = inject(API_BASE_URL) !== '';

  readonly state = signal<AsyncState<readonly TrackReply[]>>(idle());

  /** The take whose controls are open. Selecting one plays nothing. */
  readonly selected = signal<TrackReply | null>(null);
  /** Set once play is pressed, and only then. */
  readonly source = signal<string | null>(null);
  readonly fetching = signal(false);
  readonly saving = signal(false);
  readonly problem = signal<string | null>(null);

  /** Which song's takes are shown. One at a time keeps the list short. */
  readonly openSong = signal<string | null>(null);

  /** The template needs the sentinel, and a module constant is not in scope
   * there. */
  readonly ANY = ANY;

  readonly bank = signal(ANY);
  readonly level = signal(ANY);

  /** What shuffle is playing through, in order, once it has started. */
  private queue: TrackReply[] = [];

  readonly all = computed<readonly TrackReply[]>(
    () => valueOf(this.state()) ?? [],
  );

  readonly banks = computed(() =>
    [...new Set(this.all().map((t) => t.bank))].sort(),
  );

  readonly levels = computed(() =>
    [...new Set(this.all().map((t) => t.level).filter((l): l is string => !!l))].sort(),
  );

  readonly songs = computed<readonly SongGroup[]>(() => {
    const bySong = new Map<string, TrackReply[]>();
    for (const take of this.all()) {
      const found = bySong.get(take.song);
      if (found) {
        found.push(take);
      } else {
        bySong.set(take.song, [take]);
      }
    }
    return [...bySong.entries()].map(([song, takes]) => ({ song, takes }));
  });

  /** What shuffle would play, given the two choices above. */
  readonly matching = computed(() =>
    this.all().filter(
      (t) =>
        (this.bank() === ANY || t.bank === this.bank()) &&
        (this.level() === ANY || t.level === this.level()),
    ),
  );

  ngOnInit(): void {
    this.load();
  }

  ngOnDestroy(): void {
    this.release();
  }

  load(): void {
    if (!this.configured) {
      this.state.set(empty());
      return;
    }
    this.state.set(loading());
    this.library
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (reply) =>
          this.state.set(reply.tracks.length ? ready(reply.tracks) : empty()),
        error: (failure: HttpErrorResponse) =>
          this.state.set(stateForFailure(failure)),
      });
  }

  toggleSong(song: string): void {
    this.openSong.set(this.openSong() === song ? null : song);
  }

  isSelected(track: TrackReply): boolean {
    const now = this.selected();
    return !!now && keyOf(now) === keyOf(track);
  }

  /** Open the controls for a take. Deliberately does not play it. */
  select(track: TrackReply): void {
    if (this.isSelected(track)) {
      this.selected.set(null);
      this.replace(null);
      return;
    }
    this.queue = [];
    this.problem.set(null);
    this.selected.set(track);
    // Any audio already loaded belongs to the take that was open.
    this.replace(null);
  }

  play(track: TrackReply): void {
    if (this.fetching()) {
      return;
    }
    this.problem.set(null);
    this.selected.set(track);
    this.openSong.set(track.song);
    this.fetching.set(true);
    this.library
      .audio(track.song, track.bank, track.name)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.fetching.set(false);
          this.replace(URL.createObjectURL(blob));
        },
        error: (failure: HttpErrorResponse) => {
          this.fetching.set(false);
          this.replace(null);
          this.problem.set(
            isUnreachable(failure.status)
              ? 'That machine is not answering. It is a desktop, and it is not always on.'
              : (detailOf(failure) ?? `The server answered ${failure.status}.`),
          );
        },
      });
  }

  /**
   * Fetch a take and save it, without playing it.
   *
   * The bytes have to be fetched either way, because an anchor pointing at
   * the edge cannot carry the Authorization header every route needs. Saving
   * therefore looks like playing from the network's point of view and must
   * not look like it from the room's: pressing Download on a shared machine
   * should not start the music.
   */
  save(track: TrackReply): void {
    if (this.saving()) {
      return;
    }
    this.problem.set(null);
    this.saving.set(true);
    this.library
      .audio(track.song, track.bank, track.name)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.saving.set(false);
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement('a');
          anchor.href = url;
          anchor.download = track.name;
          anchor.click();
          // Revoked on the next turn rather than immediately: the click is
          // handled asynchronously, and freeing the blob first gives the
          // browser nothing to save.
          setTimeout(() => URL.revokeObjectURL(url), 0);
        },
        error: (failure: HttpErrorResponse) => {
          this.saving.set(false);
          this.problem.set(
            isUnreachable(failure.status)
              ? 'That machine is not answering. It is a desktop, and it is not always on.'
              : (detailOf(failure) ?? `The server answered ${failure.status}.`),
          );
        },
      });
  }

  /** Play everything matching the two choices, in a random order. */
  shuffle(): void {
    const pool = [...this.matching()];
    if (!pool.length) {
      return;
    }
    // Fisher-Yates. `sort(() => Math.random() - 0.5)` is the shuffle everybody
    // writes and it is not one: comparison sorts assume a consistent
    // comparator, and this leaves the first items far more likely to stay put.
    for (let i = pool.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j]!, pool[i]!];
    }
    this.queue = pool;
    this.play(pool[0]!);
  }

  /** Called when a track finishes. Shuffle continues; one take stops. */
  next(): void {
    if (!this.queue.length) {
      return;
    }
    const now = this.selected();
    const at = now ? this.queue.findIndex((t) => keyOf(t) === keyOf(now)) : -1;
    const following = this.queue[at + 1];
    if (following) {
      this.play(following);
    } else {
      this.queue = [];
    }
  }

  get shuffling(): boolean {
    return this.queue.length > 0;
  }

  size(bytes: number): string {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  private replace(url: string | null): void {
    this.release();
    this.source.set(url);
  }

  private release(): void {
    const url = this.source();
    if (url) {
      URL.revokeObjectURL(url);
    }
  }
}
