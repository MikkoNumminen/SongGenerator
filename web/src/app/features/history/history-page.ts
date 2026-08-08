import { HttpErrorResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { stateForFailure } from '../../core/api/http-failure';
import { JobReply } from '../../core/contract/dto';
import { RUN_SOURCE } from '../../core/ports/run-source.port';
import { AsyncState, empty, idle, loading, ready } from '../../core/state/async-state';
import { StatePanel } from '../../shared/state-panel/state-panel';

@Component({
  selector: 'app-history-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, StatePanel],
  templateUrl: './history-page.html',
  styleUrl: './history-page.css',
})
export class HistoryPage implements OnInit {
  private readonly runs = inject(RUN_SOURCE);
  private readonly destroyRef = inject(DestroyRef);

  readonly state = signal<AsyncState<readonly JobReply[]>>(idle());

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.state.set(loading());
    this.runs.history().pipe(takeUntilDestroyed(this.destroyRef)).subscribe({
      // An empty history is a real answer with its own wording, not a table
      // with no rows and not a spinner that never stops.
      next: (reply) =>
        this.state.set(reply.jobs.length === 0 ? empty() : ready(reply.jobs)),
      error: (error: HttpErrorResponse) => this.state.set(stateForFailure(error)),
    });
  }

  rows(): readonly JobReply[] {
    const state = this.state();
    return state.kind === 'ready' ? state.value : [];
  }

  /** Local date and time, or the raw value if it cannot be parsed. */
  when(iso: string): string {
    const at = new Date(iso);
    return Number.isNaN(at.getTime()) ? iso : at.toLocaleString();
  }
}
