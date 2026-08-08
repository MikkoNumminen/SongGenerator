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
 * the normal state of this service, not an incident.
 */
@Component({
  selector: 'app-state-panel',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @switch (state().kind) {
      @case ('loading') {
        <p class="panel" role="status" aria-live="polite">{{ busyLabel() }}</p>
      }
      @case ('offline') {
        <div class="panel offline" role="status">
          <p><strong>That machine is not answering.</strong></p>
          <p>
            The songs are made on a desktop that is not always switched on.
            Nothing is broken; there is just nothing to answer right now.
          </p>
          @if (canRetry()) {
            <button type="button" (click)="retry.emit()">Try again</button>
          }
        </div>
      }
      @case ('error') {
        <div class="panel error" role="alert">
          <p>{{ message() }}</p>
          @if (canRetry()) {
            <button type="button" (click)="retry.emit()">Try again</button>
          }
        </div>
      }
      @case ('empty') {
        <p class="panel empty">{{ emptyLabel() }}</p>
      }
      @default {
        <!-- idle and ready render nothing; ready belongs to the feature -->
      }
    }
  `,
  styles: `
    .panel { padding: 1rem 1.25rem; border-radius: 8px; margin: 0 0 1rem; }
    .offline { background: color-mix(in srgb, currentColor 6%, transparent); }
    .error { background: color-mix(in srgb, #c0392b 12%, transparent); }
    .panel p { margin: 0 0 0.5rem; }
    .panel p:last-child { margin-bottom: 0; }
    button { margin-top: 0.75rem; }
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
