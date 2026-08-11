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
import { detailOf, isUnreachable } from '../../core/api/http-failure';
import { stateForFailure } from '../../core/api/http-failure';
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

/** One song, with the renderings that exist for it. */
export interface SongGroup {
  readonly song: string;
  readonly tracks: readonly TrackReply[];
}

/**
 * Everything already made on that machine, in one list, playable.
 *
 * The audio is fetched rather than linked. An `<audio src>` cannot send an
 * Authorization header, and every route but the health check needs one, so a
 * plain src would 401 on every track. It is fetched as a Blob and played from
 * an object URL instead, which also means a download is the same bytes rather
 * than a second request.
 *
 * Object URLs are revoked when the next one replaces them and when the page
 * goes away. Each one pins its Blob in memory until it is, and a listening
 * session is dozens of tracks.
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
  /** The track being played or loaded, by its own identity. */
  readonly current = signal<TrackReply | null>(null);
  readonly source = signal<string | null>(null);
  readonly fetching = signal(false);
  readonly problem = signal<string | null>(null);

  /** Grouped by song, because a song has two renderings and they belong side
   * by side rather than as separate rows repeating the title. */
  readonly songs = computed<readonly SongGroup[]>(() => {
    const tracks = valueOf(this.state()) ?? [];
    const bySong = new Map<string, TrackReply[]>();
    for (const track of tracks) {
      const list = bySong.get(track.song);
      if (list) {
        list.push(track);
      } else {
        bySong.set(track.song, [track]);
      }
    }
    return [...bySong.entries()].map(([song, list]) => ({ song, tracks: list }));
  });

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
          this.state.set(
            reply.tracks.length ? ready(reply.tracks) : empty(),
          ),
        error: (failure: HttpErrorResponse) =>
          this.state.set(stateForFailure(failure)),
      });
  }

  /** Is this the track currently loaded into the player? */
  isCurrent(track: TrackReply): boolean {
    const now = this.current();
    return (
      !!now &&
      now.song === track.song &&
      now.bank === track.bank &&
      now.name === track.name
    );
  }

  play(track: TrackReply): void {
    if (this.fetching()) {
      return;
    }
    this.problem.set(null);
    this.fetching.set(true);
    this.current.set(track);
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
          this.current.set(null);
          this.replace(null);
          this.problem.set(
            isUnreachable(failure.status)
              ? 'That machine is not answering. It is a desktop, and it is not always on.'
              : (detailOf(failure) ?? `The server answered ${failure.status}.`),
          );
        },
      });
  }

  /** The size, for a list where every row is otherwise the same shape. */
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
