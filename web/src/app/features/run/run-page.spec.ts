import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { BehaviorSubject, Observable, of } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { JobReply } from '../../core/contract/dto';
import { RUN_SOURCE, RunSource } from '../../core/ports/run-source.port';
import { RunWatcher } from '../../core/runs/run-watcher';
import { AsyncState, ready } from '../../core/state/async-state';
import { LIBRARY } from '../../core/ports/library.port';
import { RunPage } from './run-page';

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

describe('RunPage', () => {
  let params: BehaviorSubject<ReturnType<typeof convertToParamMap>>;
  let watched: string[];
  let fixture: ComponentFixture<RunPage>;
  let cancelled: string[];

  beforeEach(() => {
    params = new BehaviorSubject(convertToParamMap({ id: 'first' }));
    watched = [];
    cancelled = [];

    const watcher = {
      watch: (id: string): Observable<AsyncState<JobReply>> => {
        watched.push(id);
        return of(ready(job({ id })));
      },
    };
    const runs: Partial<RunSource> = {
      cancel: (id: string) => {
        cancelled.push(id);
        return of(undefined);
      },
    };

    TestBed.configureTestingModule({
      imports: [RunPage],
      providers: [
      { provide: LIBRARY, useValue: { forget: () => undefined } },
        { provide: RunWatcher, useValue: watcher },
        { provide: RUN_SOURCE, useValue: runs },
        { provide: ActivatedRoute, useValue: { paramMap: params.asObservable() } },
      ],
    });
    fixture = TestBed.createComponent(RunPage);
    fixture.detectChanges();
  });

  it('watches the run in the address', () => {
    expect(watched).toEqual(['first']);
  });

  it('follows the address when it changes to another run', () => {
    // The router reuses this component when only the id changes, so ngOnInit
    // does not run again. Reading the parameter once left the page watching
    // the first run under the second one's address: a convincing way to show
    // somebody the wrong song's progress.
    params.next(convertToParamMap({ id: 'second' }));
    fixture.detectChanges();

    expect(watched).toEqual(['first', 'second']);
    expect(fixture.componentInstance.job()?.id).toBe('second');
  });

  it('does not show the previous run while the next one loads', () => {
    const watcher = TestBed.inject(RunWatcher);
    vi.spyOn(watcher, 'watch').mockReturnValue(new Observable());

    params.next(convertToParamMap({ id: 'second' }));
    fixture.detectChanges();

    expect(fixture.componentInstance.job()).toBeUndefined();
  });

  it('cancels the run it is actually showing', () => {
    params.next(convertToParamMap({ id: 'second' }));
    fixture.detectChanges();

    fixture.componentInstance.cancel();

    expect(cancelled).toEqual(['second']);
  });

  it('offers no stop button once the run has settled', () => {
    const watcher = TestBed.inject(RunWatcher);
    vi.spyOn(watcher, 'watch').mockReturnValue(of(ready(job({ stage: 'done', settled: true }))));

    params.next(convertToParamMap({ id: 'done-one' }));
    fixture.detectChanges();

    expect(fixture.componentInstance.canCancel()).toBe(false);
  });

  it('shows a stage it has never heard of instead of an empty meter', () => {
    // A newer pipeline reporting a stage this build does not list used to draw
    // five grey rows with nothing moving, which is what a stalled run looks
    // like. Where the stage belongs in the order is not knowable, so it goes
    // last and claims nothing about the ones before it.
    const watcher = TestBed.inject(RunWatcher);
    vi.spyOn(watcher, 'watch').mockReturnValue(of(ready(job({ stage: 'mixing', percent: 12 }))));

    params.next(convertToParamMap({ id: 'newer' }));
    fixture.detectChanges();

    const page = fixture.componentInstance;
    expect(page.stages()).toContain('mixing');
    expect(page.positionOf('mixing')).toBe('current');
    expect(page.positionOf('queued')).toBe('ahead');
    expect(page.fill('mixing')).toBe(12);
  });

  it('claims nothing about an unknown stage once the run has settled', () => {
    const watcher = TestBed.inject(RunWatcher);
    vi.spyOn(watcher, 'watch').mockReturnValue(of(ready(job({ stage: 'mixing', settled: true }))));

    params.next(convertToParamMap({ id: 'settled-newer' }));
    fixture.detectChanges();

    expect(fixture.componentInstance.positionOf('mixing')).toBe('ahead');
  });

  it('treats a refusal as a verdict about the song, not a failed run', () => {
    const watcher = TestBed.inject(RunWatcher);
    vi.spyOn(watcher, 'watch').mockReturnValue(of(ready(job({ stage: 'refused', settled: true }))));

    params.next(convertToParamMap({ id: 'no-vocal' }));
    fixture.detectChanges();

    expect(fixture.componentInstance.refused()).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('no vocal to borrow');
  });
});
