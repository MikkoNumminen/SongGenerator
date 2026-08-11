import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { AsyncState } from '../../core/state/async-state';

/**
 * The non-ready states, rendered once instead of in every feature.
 *
 * Each feature owns what "ready" looks like, because that is the feature. What
 * "offline" looks like is not: it is the same answer everywhere, and the one
 * state this application most needs to get right. Left to each feature it
 * drifts, and one screen ends up saying "switched off" while another shows a
 * status code for the same cause.
 *
 * The wording avoids apologising or implying fault. The desktop being off is
 * the normal state of this service, not an incident, and the panel is drawn to
 * match: a quiet card rather than the red box an error gets.
 */
@Component({
  selector: 'app-state-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @switch (state().kind) {
      @case ('loading') {
        <p class="panel panel--busy" role="status" aria-live="polite">
          <!-- Four bars keeping time. It is the mark from the header doing the
               waiting, which is cheaper than a spinner and says the same thing. -->
          <span class="bars" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
          {{ busyLabel() }}
        </p>
      }
      @case ('offline') {
        <div class="panel panel--offline" role="status">
          <svg class="glyph" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 3.5v7" />
            <path d="M17.5 6.4a7.5 7.5 0 1 1-11 0" />
          </svg>
          <div>
            <p class="title">That machine is not answering.</p>
            <p>
              The songs are made on a desktop that is not always switched on. Nothing is broken;
              there is just nothing to answer right now.
            </p>
            @if (canRetry()) {
              <button type="button" class="btn btn--sm" (click)="retry.emit()">Try again</button>
            }
          </div>
        </div>
      }
      @case ('error') {
        <div class="panel panel--error" role="alert">
          <svg class="glyph" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M12 8.2v5" />
            <path d="M12 16.4h.01" />
            <path
              d="M10.3 4.2 2.9 17.4A1.9 1.9 0 0 0 4.6 20.3h14.8a1.9 1.9 0 0 0 1.7-2.9L13.7 4.2a1.9 1.9 0 0 0-3.4 0Z"
            />
          </svg>
          <div>
            <p class="title">{{ message() }}</p>
            @if (canRetry()) {
              <button type="button" class="btn btn--sm" (click)="retry.emit()">Try again</button>
            }
          </div>
        </div>
      }
      @case ('empty') {
        <p class="panel panel--empty">{{ emptyLabel() }}</p>
      }
      @default {
        <!-- idle and ready render nothing; ready belongs to the feature -->
      }
    }
  `,
  styles: `
    /* Idle and ready draw nothing, and a host that draws nothing must not
       occupy a row: every page that uses this panel lays its children out
       with a grid gap, which an empty element would still take. */
    :host:empty {
      display: none;
    }
    .panel {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      padding: var(--space-4) var(--space-5);
      border: 1px solid var(--line);
      border-radius: var(--radius-lg);
      background: var(--surface);
      color: var(--text-muted);
      box-shadow: var(--shadow-sm);
    }
    .panel > div {
      display: grid;
      gap: var(--space-2);
      justify-items: start;
    }
    .title {
      color: var(--text);
      font-weight: 620;
    }
    .panel--offline,
    .panel--error {
      align-items: start;
    }
    .panel--error {
      border-color: color-mix(in srgb, var(--bad) 35%, transparent);
      background: color-mix(in srgb, var(--bad) 7%, var(--surface));
    }
    .panel--error .glyph {
      color: var(--bad);
    }
    .panel--empty {
      border-style: dashed;
      background: transparent;
      box-shadow: none;
      color: var(--text-faint);
    }
    .glyph {
      flex: none;
      width: 1.35rem;
      height: 1.35rem;
      margin-top: 0.15rem;
      color: var(--text-faint);
      fill: none;
      stroke: currentColor;
      stroke-width: 1.7;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .bars {
      display: flex;
      align-items: flex-end;
      gap: 2px;
      height: 1rem;
    }
    .bars i {
      width: 3px;
      height: 100%;
      border-radius: 2px;
      background: var(--accent);
      transform-origin: bottom;
      animation: bounce 1s var(--ease) infinite alternate;
    }
    .bars i:nth-child(2) {
      animation-delay: 0.12s;
    }
    .bars i:nth-child(3) {
      animation-delay: 0.24s;
    }
    .bars i:nth-child(4) {
      animation-delay: 0.36s;
    }
    @keyframes bounce {
      from {
        scale: 1 0.3;
      }
      to {
        scale: 1 1;
      }
    }
  `,
})
export class StatePanel {
  readonly state = input.required<AsyncState<unknown>>();
  readonly busyLabel = input('Loading...');
  readonly emptyLabel = input('Nothing here yet.');
  readonly canRetry = input(true);

  readonly retry = output<void>();

  message(): string {
    const state = this.state();
    return state.kind === 'error' ? state.message : '';
  }
}
