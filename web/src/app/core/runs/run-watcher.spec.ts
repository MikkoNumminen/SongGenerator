import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, Subscription, of, throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { JobReply } from '../contract/dto';
import { API_BASE_URL } from '../api/api-config';
import { RUN_SOURCE, RunSource } from '../ports/run-source.port';
import { AsyncState } from '../state/async-state';
import { OFFLINE_POLL_MS, POLL_MS, RunWatcher } from './run-watcher';

const job = (over: Partial<JobReply> = {}): JobReply => ({
  id: 'abc',
  created_at: '2026-08-08T00:00:00+00:00',
  requested_by: 'owner@example.invalid',
  source_url: 'https://example.invalid/watch?v=x',
  bank: 'ppbank',
  stage: 'rendering',
  settled: false,
  ...over,
});

/** A RunSource whose answers are scripted, one per poll. */
function scripted(answers: Array<JobReply | HttpErrorResponse>) {
  let asked = 0;
  const source: RunSource = {
    submit: () => { throw new Error('not used'); },
    history: () => { throw new Error('not used'); },
    cancel: () => { throw new Error('not used'); },
    files: () => of({ files: [] }),
    file: () => of(new Blob()),
    job: () =>
      new Observable<JobReply>((subscriber) => {
        const answer = answers[Math.min(asked, answers.length - 1)];
        asked += 1;
        if (answer instanceof HttpErrorResponse) {
          subscriber.error(answer);
        } else {
          subscriber.next(answer);
          subscriber.complete();
        }
      }),
  };
  return { source, asked: () => asked };
}

function watcherFor(answers: Array<JobReply | HttpErrorResponse>) {
  const scripts = scripted(answers);
  TestBed.configureTestingModule({
    providers: [
      { provide: RUN_SOURCE, useValue: scripts.source },
      { provide: API_BASE_URL, useValue: 'https://desk.example.invalid' },
    ],
  });
  return { watcher: TestBed.inject(RunWatcher), asked: scripts.asked };
}

describe('RunWatcher', () => {
  let sub: Subscription | undefined;

  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    sub?.unsubscribe();
    vi.useRealTimers();
  });

  const collect = (watcher: RunWatcher) => {
    const seen: AsyncState<JobReply>[] = [];
    let done = false;
    sub = watcher.watch('abc').subscribe({
      next: (state) => seen.push(state),
      complete: () => (done = true),
    });
    return { seen, isDone: () => done };
  };

  it('renders something on the first frame instead of a blank panel', () => {
    const { watcher } = watcherFor([job()]);

    const { seen } = collect(watcher);

    expect(seen[0].kind).toBe('loading');
  });

  it('keeps asking while the run is going', () => {
    const { watcher, asked } = watcherFor([job()]);
    collect(watcher);

    expect(asked()).toBe(1);
    vi.advanceTimersByTime(POLL_MS);
    expect(asked()).toBe(2);
    vi.advanceTimersByTime(POLL_MS);
    expect(asked()).toBe(3);
  });

  it('stops once the run is settled, so a finished job stops costing requests', () => {
    const { watcher, asked } = watcherFor([job(), job({ stage: 'done', settled: true })]);
    const { seen, isDone } = collect(watcher);

    vi.advanceTimersByTime(POLL_MS);

    expect(isDone()).toBe(true);
    expect(seen.at(-1)).toEqual({ kind: 'ready', value: job({ stage: 'done', settled: true }) });

    vi.advanceTimersByTime(POLL_MS * 10);
    expect(asked()).toBe(2);
  });

  it('keeps waiting when the machine goes away, because it may come back', () => {
    const offline = new HttpErrorResponse({ status: 0 });
    const { watcher, asked } = watcherFor([offline]);
    const { seen, isDone } = collect(watcher);

    vi.advanceTimersByTime(OFFLINE_POLL_MS);

    expect(seen.some((s) => s.kind === 'offline')).toBe(true);
    expect(isDone()).toBe(false);
    expect(asked()).toBe(2);
  });

  it('asks far less often while it is unreachable', () => {
    const { watcher, asked } = watcherFor([new HttpErrorResponse({ status: 0 })]);
    collect(watcher);

    // The going-rate interval must not fire an offline poll.
    vi.advanceTimersByTime(POLL_MS);
    expect(asked()).toBe(1);

    vi.advanceTimersByTime(OFFLINE_POLL_MS - POLL_MS);
    expect(asked()).toBe(2);
  });

  it('gives up on a run that will never exist', () => {
    // A 404 will not become a 200 by asking again, and retrying forever is
    // just noise on somebody's network.
    const { watcher, asked } = watcherFor([
      new HttpErrorResponse({ status: 404, error: { detail: 'no such run' } }),
    ]);
    const { seen, isDone } = collect(watcher);

    expect(isDone()).toBe(true);
    expect(seen.at(-1)).toEqual({ kind: 'error', message: 'no such run' });

    vi.advanceTimersByTime(OFFLINE_POLL_MS * 5);
    expect(asked()).toBe(1);
  });

  it('never has two requests in flight at once', () => {
    // A poll scheduled from the clock rather than from the previous answer
    // queues requests behind a slow one, and a struggling machine gets a
    // stampede exactly when it can least take it.
    let open = 0;
    let peak = 0;
    TestBed.configureTestingModule({
      providers: [
        { provide: API_BASE_URL, useValue: 'https://desk.example.invalid' },
        {
        provide: RUN_SOURCE,
        useValue: {
          submit: () => throwError(() => new Error('not used')),
          history: () => throwError(() => new Error('not used')),
          cancel: () => throwError(() => new Error('not used')),
          files: () => of({ files: [] }),
          file: () => of(new Blob()),
          job: () =>
            new Observable<JobReply>(() => {
              open += 1;
              peak = Math.max(peak, open);
              // Never answers: the machine is thinking.
              return () => (open -= 1);
            }),
        } satisfies RunSource,
      }],
    });
    const watcher = TestBed.inject(RunWatcher);
    sub = watcher.watch('abc').subscribe();

    vi.advanceTimersByTime(POLL_MS * 5);

    expect(peak).toBe(1);
  });
});
