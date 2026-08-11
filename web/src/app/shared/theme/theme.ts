import { DOCUMENT } from '@angular/common';
import { Injectable, computed, inject, signal } from '@angular/core';

/** What somebody asked for, which is not the same as what they get. */
export type ThemePreference = 'system' | 'light' | 'dark';

/** What is actually on screen. */
export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'songgen.theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

/**
 * Dark or light, and the difference between choosing one and not caring.
 *
 * `system` is kept as a real third value rather than resolved to a colour at
 * boot. Resolving it once means somebody whose machine switches to light in
 * the morning is left on last night's dark until they reload, and it also
 * writes an attribute onto a page that was rendering correctly without one.
 * Untouched, this service sets nothing and the stylesheet's own
 * `prefers-color-scheme` block does the work.
 *
 * Storage is wrapped because a browser is allowed to refuse it: private
 * windows and blocked third-party storage both throw on access rather than
 * returning null, and a theme preference is not worth a blank page.
 */
@Injectable({ providedIn: 'root' })
export class ThemeSwitch {
  private readonly document = inject(DOCUMENT);
  private readonly systemDark = signal(this.prefersDark());

  readonly preference = signal<ThemePreference>(this.stored());

  /** The theme in force: the choice, or the machine's answer when there is none. */
  readonly theme = computed<Theme>(() => {
    const chosen = this.preference();
    if (chosen !== 'system') {
      return chosen;
    }
    return this.systemDark() ? 'dark' : 'light';
  });

  constructor() {
    this.watchSystem();
    this.apply();
  }

  /** Flip to the other one, which necessarily means leaving `system` behind. */
  toggle(): void {
    this.choose(this.theme() === 'dark' ? 'light' : 'dark');
  }

  choose(preference: ThemePreference): void {
    this.preference.set(preference);
    this.remember(preference);
    this.apply();
  }

  /**
   * The attribute the stylesheet reads, or no attribute at all.
   *
   * Written from here rather than from a host binding on a component: the
   * element is `<html>`, which is outside every component in the application.
   */
  private apply(): void {
    const root = this.document.documentElement;
    const preference = this.preference();
    if (preference === 'system') {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', preference);
    }
  }

  private watchSystem(): void {
    const media = this.document.defaultView?.matchMedia?.(DARK_QUERY);
    // `addEventListener` on a media query is recent enough that a browser
    // without it is a browser this application does not otherwise run in, so
    // the absence is skipped rather than shimmed.
    media?.addEventListener?.('change', (event) => this.systemDark.set(event.matches));
  }

  private prefersDark(): boolean {
    return this.document.defaultView?.matchMedia?.(DARK_QUERY)?.matches ?? true;
  }

  private stored(): ThemePreference {
    try {
      const value = this.document.defaultView?.localStorage?.getItem(STORAGE_KEY);
      return value === 'light' || value === 'dark' ? value : 'system';
    } catch {
      return 'system';
    }
  }

  private remember(preference: ThemePreference): void {
    try {
      const storage = this.document.defaultView?.localStorage;
      if (preference === 'system') {
        storage?.removeItem(STORAGE_KEY);
      } else {
        storage?.setItem(STORAGE_KEY, preference);
      }
    } catch {
      // A refused write costs somebody the preference on their next visit and
      // nothing else. There is nothing useful to tell them about it.
    }
  }
}
