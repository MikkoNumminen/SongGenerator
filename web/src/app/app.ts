import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { BackendHealth } from './core/health/backend-health';
import { AUTH_CONTEXT } from './core/ports/auth-context.port';

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  readonly health = inject(BackendHealth);
  // Through the port, like every other component. Reaching for GoogleAuth
  // here would tie the shell to the one implementation, which is the thing
  // the ports exist to prevent.
  readonly auth = inject(AUTH_CONTEXT);

  ngOnInit(): void {
    // Asked once, at the top, so every page can render the right thing on its
    // first frame instead of each one discovering the machine is off for
    // itself.
    this.health.check().subscribe();
  }

  signIn(): void {
    void this.auth.signIn().catch(() => {
      // Sign-in failing is not a page-breaking event. The user stays signed
      // out, and every guarded route already says what that means.
    });
  }
}
