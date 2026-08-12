import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import {
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';

import { IdleSignOut } from './core/auth/idle-sign-out';
import { Membership } from './core/auth/membership';
import { standInFront } from './core/auth/stand-in-front';
import { ACCESS_REQUESTS } from './core/ports/access-requests.port';
import { Prime } from './core/data/prime';
import { BackendHealth } from './core/health/backend-health';
import { GoogleSignIn } from './core/auth/google-sign-in';
import { AUTH_CONTEXT } from './core/ports/auth-context.port';
import { ThemeToggle } from './shared/theme/theme-toggle';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs';

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
  private readonly idle = inject(IdleSignOut);
  /** Read by the template, so the bar shows only what is usable. */
  protected readonly member = inject(Membership);
  private readonly router = inject(Router);

  /**
   * Where the router is, as a signal.
   *
   * Needed because one route is meant for people this machine has not admitted
   * yet, and standing the refusal in front of it would hide the page that
   * admits them.
   */
  private readonly url = toSignal(
    this.router.events.pipe(
      filter((event) => event instanceof NavigationEnd),
      map(() => this.router.url),
    ),
    { initialValue: this.router.url },
  );

  /**
   * Whether to stand the refusal in front of the routed page.
   *
   * Not on an invitation. Somebody opening one is refused by every other route
   * on the way in, which is exactly the state the invitation exists to end, so
   * covering that page with "this machine does not know you" would hide the
   * one thing that would have let them in.
   */
  protected readonly locked = computed(() =>
    standInFront(this.member.refused(), this.url()),
  );
  private readonly access = inject(ACCESS_REQUESTS);

  /** Set while asking, and once it has been asked, for this session. */
  protected readonly asking = signal(false);
  protected readonly asked = signal(false);

  /** Put this account in the queue the owner reads. Grants nothing. */
  protected askForAccess(): void {
    if (this.asking()) {
      return;
    }
    this.asking.set(true);
    this.access.ask().subscribe({
      next: () => {
        this.asking.set(false);
        this.asked.set(true);
      },
      // Shown as asked either way. The alternative is an error box on a page
      // whose whole point is that there is nothing wrong, and the owner can
      // still be told the ordinary way.
      error: () => {
        this.asking.set(false);
        this.asked.set(true);
      },
    });
  }
  private readonly prime = inject(Prime);
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
    // Half an hour with nobody there ends the session. Started here because
    // the shell is the one thing that outlives every route.
    this.idle.start();
    // Signing in is both when the answers become gettable and when somebody
    // starts clicking. Asking once here means the first page usually finds
    // the answer already in hand.
    this.prime.start();
  }
}
