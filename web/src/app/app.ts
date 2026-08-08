import { ChangeDetectionStrategy, Component, OnInit, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { GoogleAuth } from './core/auth/google-auth';
import { BackendHealth } from './core/health/backend-health';

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  readonly health = inject(BackendHealth);
  readonly auth = inject(GoogleAuth);

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
