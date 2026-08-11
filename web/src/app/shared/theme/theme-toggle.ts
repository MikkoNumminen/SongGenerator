import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';

import { ThemeSwitch } from './theme';

/**
 * One button, showing the theme it will switch to rather than the one already
 * on screen. The icon is the action; the label says so out loud for anybody
 * who cannot see which of the two is drawn.
 */
@Component({
  selector: 'app-theme-toggle',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button
      type="button"
      class="toggle"
      [attr.aria-label]="label()"
      [title]="label()"
      (click)="themes.toggle()"
    >
      @if (themes.theme() === 'dark') {
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" />
          <g stroke-linecap="round">
            <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2" />
            <path d="M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4L17 7M7 17l-1.6 1.6" />
          </g>
        </svg>
      } @else {
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M20 14.4A8.4 8.4 0 0 1 9.6 4a8.4 8.4 0 1 0 10.4 10.4Z" />
        </svg>
      }
    </button>
  `,
  styles: `
    .toggle {
      display: grid;
      place-items: center;
      width: 2.15rem;
      height: 2.15rem;
      padding: 0;
      border: 1px solid var(--line);
      border-radius: var(--radius-pill);
      background: transparent;
      color: var(--text-muted);
      cursor: pointer;
      transition:
        color var(--fast) var(--ease),
        border-color var(--fast) var(--ease),
        background var(--fast) var(--ease);
    }
    .toggle:hover {
      color: var(--accent-text);
      border-color: color-mix(in srgb, var(--accent) 45%, transparent);
      background: var(--accent-wash);
    }
    svg {
      width: 1.05rem;
      height: 1.05rem;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.7;
    }
  `,
})
export class ThemeToggle {
  readonly themes = inject(ThemeSwitch);

  readonly label = computed(() =>
    this.themes.theme() === 'dark' ? 'Switch to the light theme' : 'Switch to the dark theme',
  );
}
