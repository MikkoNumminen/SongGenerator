import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormControl, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { BankReply } from '../../core/contract/dto';
import { stateForFailure } from '../../core/api/http-failure';
import { BackendHealth } from '../../core/health/backend-health';
import { BANK_CATALOG } from '../../core/ports/bank-catalog.port';
import { RUN_SOURCE } from '../../core/ports/run-source.port';
import { AsyncState, failed, idle, loading, ready } from '../../core/state/async-state';
import { StatePanel } from '../../shared/state-panel/state-panel';

/** A link this app is willing to send. The edge checks again; this is for typing. */
const LOOKS_LIKE_A_LINK = /^https?:\/\/\S+$/i;

/**
 * The heights of the bars under the heading, as percentages.
 *
 * Decoration, and said so plainly: it is a clip hit and decaying, not a
 * reading of anything. It is data rather than thirty-two elements typed into
 * the template because the shape is the only interesting part of it.
 */
const WAVE = [
  22, 38, 30, 54, 46, 70, 58, 84, 66, 92, 74, 100, 80, 62, 88, 54, 70, 44, 60, 36, 52, 30, 44, 26,
  38, 22, 34, 18, 28, 14, 22, 10,
] as const;

@Component({
  selector: 'app-submit-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, StatePanel],
  templateUrl: './submit-page.html',
  styleUrl: './submit-page.css',
})
export class SubmitPage implements OnInit {
  private readonly catalog = inject(BANK_CATALOG);
  private readonly runs = inject(RUN_SOURCE);
  private readonly router = inject(Router);
  readonly health = inject(BackendHealth);
  private readonly destroyRef = inject(DestroyRef);

  readonly wave = WAVE;
  readonly banks = signal<AsyncState<readonly BankReply[]>>(idle());
  readonly levels = signal<readonly string[]>([]);
  readonly submitting = signal<AsyncState<null>>(idle());

  readonly form = new FormGroup({
    source_url: new FormControl('', {
      nonNullable: true,
      validators: [Validators.required, Validators.pattern(LOOKS_LIKE_A_LINK)],
    }),
    bank: new FormControl('', { nonNullable: true, validators: [Validators.required] }),
    level: new FormControl('', { nonNullable: true }),
  });

  /** Only banks with clips built can actually sing; the rest are shown disabled. */
  readonly usableBanks = computed(() => {
    const state = this.banks();
    return state.kind === 'ready' ? state.value.filter((b) => b.usable) : [];
  });

  readonly canSubmit = computed(
    () =>
      this.health.reachable() &&
      !this.health.busy() &&
      this.usableBanks().length > 0 &&
      this.submitting().kind !== 'loading',
  );

  ngOnInit(): void {
    // Health is asked once by the shell, at the top. Asking again here spent a
    // second request on every visit to answer a question already on screen.
    //
    // With no backend configured there is nothing to ask. The address would be
    // empty, so the request would go to `/banks` on this site, which a static
    // host answers with index.html: a 200 full of HTML that arrives as a JSON
    // parse error and tells nobody anything. The shell says what is actually
    // wrong.
    if (this.health.configured) {
      this.loadBanks();
    }
  }

  loadBanks(): void {
    this.banks.set(loading());
    this.catalog
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (reply) => {
          this.levels.set(reply.levels);
          this.banks.set(ready(reply.banks));
          // Pre-pick the only sensible answer rather than making somebody choose
          // from a list of one.
          const usable = reply.banks.filter((b) => b.usable);
          if (usable.length === 1) {
            this.form.controls.bank.setValue(usable[0].name);
          }
        },
        error: (error: HttpErrorResponse) => this.banks.set(stateForFailure(error)),
      });
  }

  submit(): void {
    if (this.form.invalid || !this.canSubmit()) {
      this.form.markAllAsTouched();
      return;
    }
    const { source_url, bank, level } = this.form.getRawValue();
    this.submitting.set(loading());
    this.runs
      .submit({ source_url, bank, ...(level ? { level } : {}) })
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (job) => {
          this.submitting.set(idle());
          void this.router.navigate(['/runs', job.id]);
        },
        error: (error: HttpErrorResponse) => {
          const state = stateForFailure(error);
          // A refusal is worth keeping on screen next to the form that caused
          // it, rather than replacing the form with an error page somebody has
          // to navigate back from and retype into.
          this.submitting.set(
            state.kind === 'offline'
              ? failed('That machine stopped answering before the run started.')
              : state,
          );
        },
      });
  }
}
