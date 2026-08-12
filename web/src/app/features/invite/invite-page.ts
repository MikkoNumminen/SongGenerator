import { HttpErrorResponse } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';

import { API_BASE_URL } from '../../core/api/api-config';
import { detailOf, isUnreachable } from '../../core/api/http-failure';
import { INVITATIONS } from '../../core/ports/invitations.port';
import { AUTH_CONTEXT } from '../../core/ports/auth-context.port';

/** What this page is doing, from a stranger's point of view. */
type Step = 'waiting' | 'joining' | 'joined' | 'refused' | 'unreachable';

/**
 * The page an invitation link opens.
 *
 * The person arriving here has no account on this service and may never have
 * heard of it, so it says what the link is for before asking anything, and
 * asks for exactly one thing: signing in with Google, which is how the edge
 * learns the address to admit. The address is never typed here. It is read
 * from the token Google issues, so a link cannot be redeemed on somebody
 * else's behalf.
 *
 * Redeeming happens by itself the moment there is an identity, because at that
 * point the person has already agreed twice: once by opening the link and once
 * by signing in. A third button would be ceremony.
 */
@Component({
  selector: 'app-invite-page',
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: './invite-page.html',
  styleUrl: './invite-page.css',
})
export class InvitePage {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly invitations = inject(INVITATIONS);
  private readonly auth = inject(AUTH_CONTEXT, { optional: true });
  private readonly destroyRef = inject(DestroyRef);
  private readonly configured = inject(API_BASE_URL) !== '';

  readonly step = signal<Step>('waiting');
  readonly problem = signal<string | null>(null);

  readonly token = computed(
    () => this.route.snapshot.paramMap.get('token') ?? '',
  );

  readonly signedIn = computed(() => !!this.auth?.user());
  readonly canSignIn = computed(() => this.auth?.configured === true);

  constructor() {
    effect(() => {
      // Reading the identity is what makes this run again once somebody signs
      // in, which is the only thing this page is waiting for.
      const who = this.auth?.user()?.email ?? null;
      if (who && this.step() === 'waiting') {
        this.redeem();
      }
    });
  }

  async signIn(): Promise<void> {
    this.problem.set(null);
    try {
      await this.auth?.signIn();
    } catch {
      // Closing the Google window is a decision, not a failure.
    }
  }

  private redeem(): void {
    if (!this.configured || !this.token()) {
      this.step.set('refused');
      this.problem.set('This link is missing the part that identifies it.');
      return;
    }
    this.step.set('joining');
    this.invitations
      .accept(this.token())
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => this.step.set('joined'),
        error: (failure: HttpErrorResponse) => {
          if (isUnreachable(failure.status)) {
            this.step.set('unreachable');
            return;
          }
          this.step.set('refused');
          this.problem.set(
            failure.status === 404
              ? 'This link has already been used, or it has expired.'
              : (detailOf(failure) ?? `The server answered ${failure.status}.`),
          );
        },
      });
  }

  /** Into the demo library, which is what the invitation was for. */
  goToSongs(): void {
    void this.router.navigateByUrl('/songs');
  }
}
