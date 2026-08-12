import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { API_BASE_URL } from '../../core/api/api-config';
import { stateForFailure } from '../../core/api/http-failure';
import { JobReply } from '../../core/contract/dto';
import { RUN_SOURCE } from '../../core/ports/run-source.port';
import { loadWhenSignedIn } from '../../core/auth/load-when-signed-in';
import {
  AsyncState,
  empty,
  idle,
  loading,
  ready,
  valueOf,
} from '../../core/state/async-state';
import { RunTakes } from '../../shared/run-takes/run-takes';
import { StatePanel } from '../../shared/state-panel/state-panel';
import { stageTone } from '../../shared/stage-tone';

/** The sentinel for "not narrowed to anybody". */
const EVERYONE = '__everyone__';

@Component({
  selector: 'app-history-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, StatePanel, RunTakes],
  templateUrl: './history-page.html',
  styleUrl: './history-page.css',
})
export class HistoryPage {

  constructor() {
    // Not ngOnInit: the identity arrives after the page does, and asking
    // before it has is the 401 that used to leave a "Try again" button.
    loadWhenSignedIn(() => this.load());
  }
  private readonly runs = inject(RUN_SOURCE);
  private readonly destroyRef = inject(DestroyRef);
  private readonly configured = inject(API_BASE_URL) !== '';

  readonly state = signal<AsyncState<readonly JobReply[]>>(idle());

  /** Which run's takes are showing. One at a time keeps the table a table. */
  readonly openRun = signal<string | null>(null);

  toggle(id: string): void {
    this.openRun.set(this.openRun() === id ? null : id);
  }

  /** Everybody, or one address. Only offered to somebody who sees all runs. */
  readonly showing = signal<string>(EVERYONE);

  /** The addresses worth offering: whoever actually asked for a run. */
  readonly askers = computed(() => {
    const jobs: readonly JobReply[] = valueOf(this.state()) ?? [];
    return [...new Set(jobs.map((j) => j.requested_by))].sort();
  });

  readonly EVERYONE = EVERYONE;

  /** Narrow to one person's runs, or widen back to everybody's. */
  show(who: string): void {
    this.showing.set(who);
    this.load();
  }

  load(): void {
    // Nothing to read from. An empty address would request `/jobs` on this
    // site, which a static host answers with index.html.
    if (!this.configured) {
      this.state.set(empty());
      return;
    }
    this.state.set(loading());
    const only = this.showing();
    this.runs
      .history(undefined, only === EVERYONE ? undefined : only)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        // An empty history is a real answer with its own wording, not a table
        // with no rows and not a spinner that never stops.
        next: (reply) => this.state.set(reply.jobs.length === 0 ? empty() : ready(reply.jobs)),
        error: (error: HttpErrorResponse) => this.state.set(stateForFailure(error)),
      });
  }

  rows(): readonly JobReply[] {
    const state = this.state();
    return state.kind === 'ready' ? state.value : [];
  }

  /** The badge colour for an outcome. Shared with the run page. */
  readonly toneFor = stageTone;

  /** Local date and time, or the raw value if it cannot be parsed. */
  when(iso: string): string {
    const at = new Date(iso);
    return Number.isNaN(at.getTime()) ? iso : at.toLocaleString();
  }
}
