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

import { API_BASE_URL } from '../../core/api/api-config';
import { detailOf, isUnreachable, stateForFailure } from '../../core/api/http-failure';
import { UsersReply } from '../../core/contract/dto';
import { ALLOWLIST } from '../../core/ports/allowlist.port';
import { AUTH_CONTEXT } from '../../core/ports/auth-context.port';
import { loadWhenSignedIn } from '../../core/auth/load-when-signed-in';
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
export class AdminPage {

  constructor() {
    // Not ngOnInit: the identity arrives after the page does, and asking
    // before it has is the 401 that used to leave a "Try again" button.
    loadWhenSignedIn(() => this.load());
  }
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
   * Why one action failed, in the edge's own words where it wrote them.
   *
   * Uses the shared helpers rather than reading `detail` here. `detailOf`
   * deliberately ignores a plain-string body, because the edge always answers
   * with JSON and a string came from something in between: a tunnel or a
   * proxy, whose body is usually a whole HTML page. Reading the field
   * directly, as this did, would put markup in front of the reader as if the
   * server had written them a sentence. It also knows that 502, 503 and 504
   * mean the desktop is off, not that something broke.
   */
  private explain(failure: HttpErrorResponse): string {
    if (isUnreachable(failure.status)) {
      return 'That machine is not answering. It is a desktop, and it is not always on.';
    }
    return detailOf(failure) ?? `The server answered ${failure.status}.`;
  }
}
