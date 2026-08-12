import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnDestroy,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { detailOf, isUnreachable } from '../../core/api/http-failure';
import { FileReply } from '../../core/contract/dto';
import { RUN_SOURCE } from '../../core/ports/run-source.port';

/**
 * What a run produced, with a way to hear it and a way to keep it.
 *
 * A finished run used to say only that files had been written and where they
 * sat on disk, which is no use to anybody reading it in a browser on another
 * machine. The same thing is wanted in two places, on the run itself and
 * against a row in the history, so it is one component rather than two that
 * drift.
 *
 * Nothing is fetched until the run has finished. While it is going there is
 * nothing to list, and asking would be a request per poll.
 */
@Component({
  selector: 'app-run-takes',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './run-takes.html',
  styleUrl: './run-takes.css',
})
export class RunTakes implements OnDestroy {
  private readonly runs = inject(RUN_SOURCE);
  private readonly destroyRef = inject(DestroyRef);

  /** Which run. */
  readonly runId = input.required<string>();
  /** Whether it has finished. Nothing is fetched until it has. */
  readonly finished = input(false);

  readonly takes = signal<readonly FileReply[]>([]);
  /** The take being played, and the object URL it is playing from. */
  readonly playing = signal<string | null>(null);
  readonly source = signal<string | null>(null);
  readonly busy = signal<string | null>(null);
  readonly problem = signal<string | null>(null);

  private asked: string | null = null;

  constructor() {
    effect(() => {
      const id = this.runId();
      if (!this.finished() || this.asked === id) {
        return;
      }
      this.asked = id;
      this.runs
        .files(id)
        .pipe(takeUntilDestroyed(this.destroyRef))
        .subscribe({
          next: (reply) => this.takes.set(reply.files),
          // Quietly. A run that produced nothing readable is not an error
          // worth a red box next to a run that finished.
          error: () => this.takes.set([]),
        });
    });
  }

  ngOnDestroy(): void {
    this.release();
  }

  /** Fetch and play one. Pressing the one already playing stops it. */
  play(take: FileReply): void {
    if (this.busy()) {
      return;
    }
    if (this.playing() === take.name) {
      this.playing.set(null);
      this.replace(null);
      return;
    }
    this.problem.set(null);
    this.busy.set(take.name);
    this.runs
      .file(this.runId(), take.name)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.busy.set(null);
          this.playing.set(take.name);
          this.replace(URL.createObjectURL(blob));
        },
        error: (failure: HttpErrorResponse) => this.refuse(failure),
      });
  }

  /**
   * Fetch and save one, without playing it.
   *
   * The bytes have to be fetched either way, because an anchor pointing at the
   * edge cannot carry the Authorization header. Saving therefore looks like
   * playing from the network's side and must not from the room's.
   */
  save(take: FileReply): void {
    if (this.busy()) {
      return;
    }
    this.problem.set(null);
    this.busy.set(take.name);
    this.runs
      .file(this.runId(), take.name)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (blob) => {
          this.busy.set(null);
          const url = URL.createObjectURL(blob);
          const anchor = document.createElement('a');
          anchor.href = url;
          anchor.download = take.name;
          anchor.click();
          // Revoked next turn: the click is handled asynchronously, and
          // freeing it first gives the browser nothing to save.
          setTimeout(() => URL.revokeObjectURL(url), 0);
        },
        error: (failure: HttpErrorResponse) => this.refuse(failure),
      });
  }

  size(bytes: number): string {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  private refuse(failure: HttpErrorResponse): void {
    this.busy.set(null);
    this.problem.set(
      isUnreachable(failure.status)
        ? 'That machine is not answering. It is a desktop, and it is not always on.'
        : (detailOf(failure) ?? `The server answered ${failure.status}.`),
    );
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
