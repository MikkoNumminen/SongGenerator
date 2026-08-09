import { Injectable, InjectionToken, computed, inject, signal } from '@angular/core';

import { AuthContext, SignedInUser } from '../ports/auth-context.port';
import { IdTokenClaims, isExpired, readClaims } from './id-token';

/**
 * The Google client id this deployment signs in with.
 *
 * Empty means sign-in is not set up. That is a real state rather than a
 * mistake to crash on: a fresh clone has no client id, and the app should say
 * so plainly instead of showing a button that fails silently.
 */
export const GOOGLE_CLIENT_ID = new InjectionToken<string>('GOOGLE_CLIENT_ID', {
  providedIn: 'root',
  factory: () => '',
});

/** The slice of Google Identity Services this uses. */
interface GoogleIdentity {
  accounts: {
    id: {
      initialize(config: {
        client_id: string;
        callback: (response: { credential?: string }) => void;
        auto_select?: boolean;
      }): void;
      prompt(): void;
      renderButton(parent: HTMLElement, options: {
        type?: 'standard' | 'icon';
        theme?: 'outline' | 'filled_blue' | 'filled_black';
        size?: 'large' | 'medium' | 'small';
        text?: 'signin_with' | 'signup_with' | 'continue_with';
        shape?: 'rectangular' | 'pill';
      }): void;
      disableAutoSelect(): void;
    };
  };
}

declare const google: GoogleIdentity | undefined;

const SCRIPT_URL = 'https://accounts.google.com/gsi/client';

/**
 * How long to wait for Google's script before calling it unavailable.
 *
 * Generous, because a slow connection is not a broken one, and the page is
 * usable without signing in while this runs. It exists so the wait is bounded
 * at all: a request that is silently dropped rather than refused produces no
 * error event, and the button would otherwise say "loading" indefinitely.
 */
const LOAD_TIMEOUT_MS = 15_000;

/**
 * Sign-in, as far as a browser is allowed to be involved in it.
 *
 * This carries a token and nothing more. Whether the person holding it may
 * use the service is decided by the edge, against an allowlist of specific
 * accounts, because the pipeline takes an arbitrary link and spends a GPU on
 * it and must never be openly usable. A check here would be advice; a check
 * there is the rule.
 *
 * The script is loaded on first use rather than in index.html, so a page that
 * nobody signs in on makes no request to Google at all.
 */
@Injectable({ providedIn: 'root' })
export class GoogleAuth implements AuthContext {
  private readonly clientId = inject(GOOGLE_CLIENT_ID);

  private readonly claims = signal<IdTokenClaims | null>(null);
  private raw: string | null = null;
  private loading: Promise<void> | null = null;
  private initialised = false;

  readonly user = computed<SignedInUser | null>(() => {
    const claims = this.claims();
    if (!claims) {
      return null;
    }
    return { email: claims.email, ...(claims.name ? { name: claims.name } : {}) };
  });

  /** Whether this deployment can sign anybody in at all. */
  readonly configured = this.clientId !== '';

  /**
   * The token, or null when there is not a usable one.
   *
   * Expiry is checked on every read rather than on a timer. A timer that
   * fires while the tab is asleep proves nothing, and the only moment the
   * answer matters is when a request is about to be sent.
   */
  token(): string | null {
    const claims = this.claims();
    if (!claims || !this.raw) {
      return null;
    }
    if (isExpired(claims)) {
      this.forget();
      return null;
    }
    return this.raw;
  }

  /**
   * Put Google's own button in `element`.
   *
   * This is the way in, rather than One Tap. `prompt()` is suppressed often
   * and quietly: a cooldown after somebody dismissed it once, third-party
   * cookie rules, a browser that has moved to FedCM. When it is suppressed it
   * does nothing at all, so a person clicks Sign in and the page sits there.
   * A rendered button is the flow Google treats as primary, and it is visibly
   * present or visibly absent.
   *
   * Throws if it cannot be shown, so a caller can say so instead of leaving an
   * empty space where a button should be.
   */
  async mountButton(element: HTMLElement): Promise<void> {
    const identity = await this.ready();
    identity.accounts.id.renderButton(element, {
      type: 'standard',
      theme: 'outline',
      size: 'large',
      text: 'signin_with',
      shape: 'rectangular',
    });
  }

  /**
   * One Tap, offered on top of the button rather than instead of it.
   *
   * Kept because the port declares it and because when it does appear it is
   * the shortest path in. Nothing depends on it working.
   */
  async signIn(): Promise<void> {
    const identity = await this.ready();
    identity.accounts.id.prompt();
  }

  private async ready(): Promise<GoogleIdentity> {
    if (!this.configured) {
      throw new Error(
        'Sign-in is not configured for this deployment: no Google client id.',
      );
    }
    await this.loadScript();
    if (typeof google === 'undefined') {
      throw new Error('Google sign-in could not be loaded.');
    }
    // Once, however many entry points ask. Both the button and One Tap need
    // the library initialised, and calling it twice is not harmless as an
    // earlier comment here claimed: Google logs "initialize() is called
    // multiple times ... only the last initialized instance will be used",
    // which was visible in the console of the deployed site.
    if (!this.initialised) {
      google.accounts.id.initialize({
        client_id: this.clientId,
        callback: (response) => this.accept(response.credential),
      });
      this.initialised = true;
    }
    return google;
  }

  signOut(): void {
    if (typeof google !== 'undefined') {
      google.accounts.id.disableAutoSelect();
    }
    this.forget();
  }

  /**
   * Take a credential from Google. Exposed for the callback and for tests,
   * which have no business driving a real sign-in dialog.
   */
  accept(credential: string | undefined): void {
    const claims = credential ? readClaims(credential) : null;
    // A token whose claims cannot be read is not kept. Sending it would spend
    // a request to be told 401 by a server that can read it properly.
    if (!claims || isExpired(claims)) {
      this.forget();
      return;
    }
    this.raw = credential ?? null;
    this.claims.set(claims);
  }

  private forget(): void {
    this.raw = null;
    this.claims.set(null);
  }

  private loadScript(): Promise<void> {
    if (typeof google !== 'undefined') {
      return Promise.resolve();
    }
    // One load, however many callers ask. Two script tags would register two
    // callbacks and sign in twice.
    this.loading ??= new Promise<void>((resolve, reject) => {
      // Whatever happens, this settles. A promise that never does leaves the
      // button on "Loading sign-in..." for as long as the page is open, which
      // is the empty-space failure this component exists to avoid, wearing a
      // different hat.
      const timer = setTimeout(() => {
        fail(new Error('Google sign-in did not load in time.'));
      }, LOAD_TIMEOUT_MS);

      const done = () => {
        clearTimeout(timer);
        resolve();
      };
      // Clearing `loading` on the way out is what lets a later attempt try
      // again. Leaving the rejected promise cached meant the first failure was
      // permanent: every subsequent call returned the same rejection, so a
      // blocked extension or a dropped connection could never be recovered
      // from without a reload.
      const fail = (error: Error) => {
        clearTimeout(timer);
        this.loading = null;
        reject(error);
      };

      // A tag somebody else put there, or one from a previous attempt. Its
      // load event may already have fired, in which case listening for it
      // waits forever; the timeout is what bounds that case.
      const existing = document.querySelector<HTMLScriptElement>(
        `script[src="${SCRIPT_URL}"]`,
      );
      if (existing) {
        existing.addEventListener('load', done);
        existing.addEventListener('error', () =>
          fail(new Error('Google sign-in could not be loaded.')),
        );
        return;
      }
      const script = document.createElement('script');
      script.src = SCRIPT_URL;
      script.async = true;
      script.onload = done;
      script.onerror = () => fail(new Error('Google sign-in could not be loaded.'));
      document.head.appendChild(script);
    });
    return this.loading;
  }
}
