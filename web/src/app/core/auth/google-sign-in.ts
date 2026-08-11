import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  inject,
  signal,
  viewChild,
} from '@angular/core';

import { GoogleAuth } from './google-auth';

/**
 * Google's own sign-in button, and an honest answer when it will not appear.
 *
 * This is the one component in `core`, and it is here rather than in `shared`
 * because it is not presentational: Google renders into the element itself,
 * from a script this adapter loads, using a client id only this adapter knows.
 * A version that took all of that through inputs would be the same code with
 * an extra hop, and `shared` would then know what Google is.
 *
 * The states matter more than the button. A sign-in that quietly fails to draw
 * leaves somebody clicking an empty space, which is the failure this whole
 * application is arranged to avoid.
 */
@Component({
  selector: 'app-google-sign-in',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div #host class="host"></div>
    @switch (state()) {
      @case ('loading') {
        <span class="note">Loading sign-in...</span>
      }
      @case ('unavailable') {
        <span class="note">
          Google sign-in could not be loaded. It may be blocked here, or
          offline.
        </span>
      }
      @case ('unconfigured') {
        <span class="note" title="No Google client id is set for this deployment">
          Sign-in is not set up on this site.
        </span>
      }
      @default {}
    }
  `,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
    }
    /* Google draws its own button and owns how it looks. What is styled here
       is only the sentence that appears when it does not. */
    .note {
      max-width: 16rem;
      color: var(--text-faint);
      font-size: var(--text-xs);
      line-height: 1.35;
    }
  `,
})
export class GoogleSignIn implements AfterViewInit {
  private readonly auth = inject(GoogleAuth);
  private readonly host = viewChild.required<ElementRef<HTMLElement>>('host');

  readonly state = signal<'loading' | 'ready' | 'unavailable' | 'unconfigured'>(
    'loading',
  );

  async ngAfterViewInit(): Promise<void> {
    if (!this.auth.configured) {
      this.state.set('unconfigured');
      return;
    }
    try {
      await this.auth.mountButton(this.host().nativeElement);
      this.state.set('ready');
      // One Tap on top, once the button is definitely there. It is the
      // shortest way in when it appears and nothing depends on it.
      void this.auth.signIn().catch(() => undefined);
    } catch {
      // Blocked by an extension, an offline browser, a network that eats
      // requests to Google. All of them mean the same thing to somebody
      // looking at the page, and none is worth a stack trace.
      this.state.set('unavailable');
    }
  }
}
