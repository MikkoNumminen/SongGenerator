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

import { API_BASE_URL } from '../../core/api/api-config';
import { stateForFailure } from '../../core/api/http-failure';
import { UsersReply } from '../../core/contract/dto';
import { ALLOWLIST } from '../../core/ports/allowlist.port';
import { AUTH_CONTEXT } from '../../core/ports/auth-context.port';
import {
  AsyncState,
  empty,
  idle,
  loading,
  ready,
  valueOf,
} from '../../core/state/async-state';
import { StatePanel } from '../../shared/state-panel/state-panel';

/**
 * Who may use this service, and the one page that changes it.
 *
 * The page shows itself to anybody signed in and then reports honestly what
 * the edge says. It does not hide behind a client-side role check, because a
 * hidden button is not a permission: the edge answers 403 to a caller who is
 * not an administrator whatever this renders, and that answer is what is
 * shown. The alternative invites the belief that hiding the page is the
 * security.
 */
@Component({
  selector: 'app-admin-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [StatePanel],
  templateUrl: './admin-page.html',
  styleUrl: './admin-page.css',
})
export class AdminPage implements OnInit {
  private readonly allowlist = inject(ALLOWLIST);
  private readonly auth = inject(AUTH_CONTEXT, { optional: true });
  private readonly destroyRef = inject(DestroyRef);
  private readonly configured = inject(API_BASE_URL) !== '';

  readonly state = signal<AsyncState<UsersReply>>(idle());
  readonly typed = signal('');
  /** Set while a grant or revoke is in flight, to stop a double submit. */
  readonly working = signal(false);
  /** A refusal from the edge, kept apart from the list's own state. */
  readonly problem = signal<string | null>(null);

  /** The reply when there is one. Undefined in every other state. */
  readonly value = computed(() => valueOf(this.state()));

  /** The signed-in address, so the list can say which row is you. */
  readonly me = computed(() => this.auth?.user()?.email ?? null);

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    if (!this.configured) {
      this.state.set(empty());
      return;
    }
    this.state.set(loading());
    this.allowlist
      .list()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (reply) => this.state.set(ready(reply)),
        error: (failure: HttpErrorResponse) =>
          this.state.set(stateForFailure(failure)),
      });
  }

  grant(): void {
    const email = this.typed().trim().toLowerCase();
    if (!email || this.working()) {
      return;
    }
    this.problem.set(null);
    this.working.set(true);
    this.allowlist
      .grant(email)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.typed.set('');
          this.working.set(false);
          // Re-read rather than patching the list locally. The edge decides
          // what the list is, including whether this address was already on
          // it, and a local guess would drift from that on the first surprise.
          this.load();
        },
        error: (failure: HttpErrorResponse) => {
          this.working.set(false);
          this.problem.set(this.explain(failure));
        },
      });
  }

  revoke(email: string): void {
    if (this.working()) {
      return;
    }
    this.problem.set(null);
    this.working.set(true);
    this.allowlist
      .revoke(email)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (reply) => {
          this.working.set(false);
          this.state.set(ready(reply));
        },
        error: (failure: HttpErrorResponse) => {
          this.working.set(false);
          this.problem.set(this.explain(failure));
        },
      });
  }

  /**
   * The edge's own sentence where it wrote one.
   *
   * It explains things this page cannot know: that an address is an
   * administrator set in the machine's configuration and cannot be revoked
   * from here, or that the caller is not an administrator at all. Replacing
   * those with a generic message would throw away the only explanation.
   */
  private explain(failure: HttpErrorResponse): string {
    const detail = failure.error?.detail;
    if (typeof detail === 'string' && detail) {
      return detail;
    }
    return failure.status === 0
      ? 'That machine is not answering.'
      : `The request failed (${failure.status}).`;
  }
}
