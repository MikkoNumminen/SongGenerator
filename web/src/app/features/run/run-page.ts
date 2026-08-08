import { ChangeDetectionStrategy, Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import { Subscription } from 'rxjs';

import { JobReply } from '../../core/contract/dto';
import { RUN_SOURCE } from '../../core/ports/run-source.port';
import { RunWatcher } from '../../core/runs/run-watcher';
import { AsyncState, idle, valueOf } from '../../core/state/async-state';
import { StatePanel } from '../../shared/state-panel/state-panel';

/**
 * The stages the pipeline actually reports, in the order it reaches them.
 *
 * Listed rather than derived, because the bar has to show a stage that has not
 * been reached yet, and a run that refuses at mode B never reaches most of
 * them. Kept as data so an unknown stage from a newer pipeline renders as
 * itself instead of breaking the page.
 */
const STAGES = ['queued', 'separating', 'analysing', 'arranging', 'rendering'] as const;

@Component({
  selector: 'app-run-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [StatePanel],
  templateUrl: './run-page.html',
  styleUrl: './run-page.css',
})
export class RunPage implements OnInit, OnDestroy {
  private readonly route = inject(ActivatedRoute);
  private readonly watcher = inject(RunWatcher);
  private readonly runs = inject(RUN_SOURCE);

  private readonly destroyRef = inject(DestroyRef);
  private watching?: Subscription;
  private current: string | null = null;

  readonly stages = STAGES;
  readonly state = signal<AsyncState<JobReply>>(idle());
  readonly cancelling = signal(false);

  readonly job = computed(() => valueOf(this.state()));

  /** A refusal is a real answer about the song, not a failure of the run. */
  readonly refused = computed(() => this.job()?.stage === 'refused');

  readonly finished = computed(() => this.job()?.settled === true);

  readonly canCancel = computed(
    () => this.job() !== undefined && !this.finished() && !this.cancelling(),
  );

  ngOnInit(): void {
    // The parameter is followed rather than read once. The router reuses this
    // component when only the id changes, so ngOnInit does not run again:
    // reading a snapshot meant going from one run to another left the page
    // watching the first one under the second one's address, which is a
    // convincing way to show somebody the wrong song's progress.
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const id = params.get('id');
      this.current = id;
      if (id) {
        this.watch(id);
      }
    });
  }

  ngOnDestroy(): void {
    // Leaving the page stops the polling. Without this a tab left open on an
    // old run keeps asking a desktop about it for as long as the tab lives.
    this.watching?.unsubscribe();
  }

  watch(id: string): void {
    this.watching?.unsubscribe();
    this.state.set(idle());
    this.watching = this.watcher.watch(id).subscribe((state) => this.state.set(state));
  }

  retry(): void {
    if (this.current) {
      this.watch(this.current);
    }
  }

  cancel(): void {
    const job = this.job();
    if (!job) {
      return;
    }
    this.cancelling.set(true);
    this.runs.cancel(job.id).subscribe({
      // Either way the watcher reports what really happened next tick, so
      // nothing here pretends to know the outcome. A cancel that arrives just
      // after a run finished is a 409, and that is not worth a red box.
      next: () => this.cancelling.set(false),
      error: () => this.cancelling.set(false),
    });
  }

  /** How far along a stage is: done, current, or still ahead. */
  positionOf(stage: string): 'done' | 'current' | 'ahead' {
    const job = this.job();
    if (!job) {
      return 'ahead';
    }
    const at = STAGES.indexOf(job.stage as (typeof STAGES)[number]);
    const mine = STAGES.indexOf(stage as (typeof STAGES)[number]);
    // Settled runs never reached a stage after the one they stopped at, and a
    // finished run has passed all of them.
    if (job.stage === 'done') {
      return 'done';
    }
    if (at < 0) {
      return 'ahead';
    }
    return mine < at ? 'done' : mine === at ? 'current' : 'ahead';
  }
}
