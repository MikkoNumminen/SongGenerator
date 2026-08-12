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
import {
  InvitationReply,
  UserReply,
  UsersReply,
} from '../../core/contract/dto';
/** The library everybody starts with. Named on the edge; repeated here only
 * so the panel can tick the right box before anything has been fetched. */
const DEMO = 'demo';

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
    loadWhenSignedIn(() => {
      this.load();
      this.readInvitations();
    });
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

  /**
   * What the next grant will include. Starts at the demo library alone.
   *
   * A stranger is a stranger, so the box that is already ticked is the one
   * that gives away the least, and widening is a deliberate click rather than
   * whatever the last grant happened to leave behind.
   */
  readonly wanted = signal<readonly string[]>([DEMO]);

  toggleWanted(name: string): void {
    const now = this.wanted();
    this.wanted.set(now.includes(name)
      ? now.filter((b) => b !== name)
      : [...now, name]);
  }

  /** Outstanding invitations, and the one just made. */
  readonly invitations = signal<readonly InvitationReply[]>([]);
  /** The link just created, shown once so it can be copied and sent. */
  readonly freshLink = signal<string | null>(null);
  readonly copied = signal(false);

  /** The address a link is opened at, built from where this page is served. */
  linkFor(token: string): string {
    return `${location.origin}${location.pathname.replace(/\/[^/]*$/, '')}/invite/${token}`;
  }

  readInvitations(): void {
    this.allowlist
      .invitations()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (reply) => this.invitations.set(reply.invitations),
        // Quietly: the panel's main job is the allowlist, and a failure to
        // read invitations should not replace the list with an error.
        error: () => this.invitations.set([]),
      });
  }

  invite(): void {
    if (this.working()) {
      return;
    }
    this.problem.set(null);
    this.copied.set(false);
    this.working.set(true);
    this.allowlist
      .invite()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (made) => {
          this.working.set(false);
          this.freshLink.set(this.linkFor(made.token));
          this.readInvitations();
        },
        error: (failure: HttpErrorResponse) => {
          this.working.set(false);
          this.problem.set(this.explain(failure));
        },
      });
  }

  async copyLink(): Promise<void> {
    const link = this.freshLink();
    if (!link) {
      return;
    }
    try {
      await navigator.clipboard.writeText(link);
      this.copied.set(true);
    } catch {
      // Refused, or no clipboard. The link is on screen and selectable, so
      // there is nothing to recover from and nothing worth an alarm.
      this.copied.set(false);
    }
  }

  withdraw(token: string): void {
    if (this.working()) {
      return;
    }
    this.working.set(true);
    this.allowlist
      .withdraw(token)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (reply) => {
          this.working.set(false);
          this.invitations.set(reply.invitations);
          this.freshLink.set(null);
        },
        error: (failure: HttpErrorResponse) => {
          this.working.set(false);
          this.problem.set(this.explain(failure));
        },
      });
  }

  /** Grant or withdraw seeing everybody's runs. */
  toggleRuns(user: UserReply): void {
    if (this.working()) {
      return;
    }
    this.problem.set(null);
    this.working.set(true);
    this.allowlist
      .setSeesAllRuns(user.email, !user.see_all_runs)
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

  /** Change one box on an address that already has access. */
  toggleFor(user: UserReply, name: string): void {
    if (this.working()) {
      return;
    }
    const next = user.banks.includes(name)
      ? user.banks.filter((b) => b !== name)
      : [...user.banks, name];
    this.problem.set(null);
    this.working.set(true);
    this.allowlist
      .setBanks(user.email, next)
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
      .grant(email, this.wanted())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          this.typed.set('');
          this.wanted.set([DEMO]);
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
