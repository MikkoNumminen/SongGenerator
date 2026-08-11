import { ChangeDetectionStrategy, Component, OnInit, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { BackendHealth } from './core/health/backend-health';
import { GoogleSignIn } from './core/auth/google-sign-in';
import { AUTH_CONTEXT } from './core/ports/auth-context.port';
import { ThemeToggle } from './shared/theme/theme-toggle';

/**
 * The one-line answer to "is the machine on", as a colour and three words.
 *
 * `tone` picks the badge's colour and nothing else, so the six cases collapse
 * to three appearances without any of them losing its own wording.
 */
interface MachineState {
  readonly tone: 'ok' | 'busy' | 'bad' | 'idle';
  readonly label: string;
  readonly title: string;
}

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, GoogleSignIn, ThemeToggle],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  readonly health = inject(BackendHealth);
  // Through the port, like every other component. Reaching for GoogleAuth
  // here would tie the shell to the one implementation, which is the thing
  // the ports exist to prevent.
  readonly auth = inject(AUTH_CONTEXT);

  /**
   * The same six states the panels render, said in a glance.
   *
   * It is in the header rather than only in a banner because the answer is
   * the context for everything else on the page: a disabled button means one
   * thing when the machine is awake and another when it is not, and somebody
   * who has read the banner once should not have to scroll back for it.
   */
  readonly machine = computed<MachineState>(() => {
    if (!this.health.configured) {
      return {
        tone: 'bad',
        label: 'no backend',
        title: 'This site has not been told where its backend is.',
      };
    }
    const state = this.health.status();
    if (state.kind === 'idle' || state.kind === 'loading') {
      return { tone: 'idle', label: 'asking', title: 'Asking the machine whether it is awake.' };
    }
    if (state.kind !== 'ready') {
      return { tone: 'idle', label: 'asleep', title: 'The machine is not answering.' };
    }
    if (this.health.busy()) {
      return { tone: 'busy', label: 'making one', title: 'A run is going right now.' };
    }
    if (!this.health.authConfigured()) {
      return {
        tone: 'bad',
        label: 'no allowlist',
        title: 'That machine has nobody allowed to sign in.',
      };
    }
    return { tone: 'ok', label: 'awake', title: 'The machine is on and free.' };
  });

  ngOnInit(): void {
    // Asked once, at the top, so every page can render the right thing on its
    // first frame instead of each one discovering the machine is off for
    // itself.
    this.health.check().subscribe();
  }
}
