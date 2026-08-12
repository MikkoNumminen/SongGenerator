import { Injectable, computed, signal } from '@angular/core';

/**
 * Whether the signed-in account has actually been let in.
 *
 * Signing in with Google says who somebody is. It says nothing about whether
 * this machine admits them, and only the edge knows that. Until it has
 * answered, the browser genuinely does not know, and drawing a full navigation
 * on that guess is how somebody ends up clicking four things that all refuse
 * them.
 *
 * The answer comes from requests that were being made anyway: 403 means signed
 * in and not admitted, anything that succeeds means admitted. Nothing here
 * asks a question of its own.
 */
export type Standing = 'unknown' | 'admitted' | 'refused';

@Injectable({ providedIn: 'root' })
export class Membership {
  private readonly state = signal<Standing>('unknown');

  readonly standing = this.state.asReadonly();
  readonly admitted = computed(() => this.state() === 'admitted');
  readonly refused = computed(() => this.state() === 'refused');

  /** A request the edge answered. */
  saw(status: number): void {
    if (status === 403) {
      this.state.set('refused');
      return;
    }
    // 401 is left alone on purpose: it means the token is missing or stale,
    // which is a sign-in problem rather than a verdict about the account, and
    // treating it as refusal would offer to request access somebody may
    // already have.
    if (status >= 200 && status < 300) {
      this.state.set('admitted');
    }
  }

  /** Nobody is signed in, so there is nothing to know. */
  forget(): void {
    this.state.set('unknown');
  }
}
