import { HttpErrorResponse } from '@angular/common/http';
import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Observable, of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import { FilesReply } from '../../core/contract/dto';
import { RUN_SOURCE, RunSource } from '../../core/ports/run-source.port';
import { RunTakes } from './run-takes';

const TAKES = {
  files: [
    { name: 'song.conservative.mp3', level: 'conservative', bytes: 3_000_000 },
    { name: 'song.wild.mp3', level: 'wild', bytes: 3_100_000 },
  ],
};

class FakeRuns implements Partial<RunSource> {
  asked: string[] = [];
  fetched: string[] = [];
  failFileWith: HttpErrorResponse | null = null;

  files(id: string): Observable<FilesReply> {
    this.asked.push(id);
    return of(TAKES);
  }

  file(id: string, name: string): Observable<Blob> {
    this.fetched.push(name);
    return this.failFileWith
      ? throwError(() => this.failFileWith)
      : of(new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/mpeg' }));
  }
}

@Component({
  selector: 'app-host',
  imports: [RunTakes],
  template: '<app-run-takes [runId]="id()" [finished]="done()" />',
})
class Host {
  readonly id = signal('a-run');
  readonly done = signal(true);
}

async function render(runs: FakeRuns, finished = true) {
  TestBed.configureTestingModule({
    imports: [Host],
    providers: [{ provide: RUN_SOURCE, useValue: runs }],
  });
  const fixture: ComponentFixture<Host> = TestBed.createComponent(Host);
  fixture.componentInstance.done.set(finished);
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
}

function takes(fixture: ComponentFixture<Host>): RunTakes {
  return fixture.debugElement.children[0].componentInstance as RunTakes;
}

describe('what a run made', () => {
  it('asks for nothing while the run is still going', async () => {
    // There is nothing to list yet, and asking would be a request per poll.
    const runs = new FakeRuns();

    await render(runs, false);

    expect(runs.asked).toEqual([]);
  });

  it('lists what it produced once it has finished', async () => {
    const runs = new FakeRuns();

    const fixture = await render(runs);

    expect(runs.asked).toEqual(['a-run']);
    expect(takes(fixture).takes().map((t) => t.level))
      .toEqual(['conservative', 'wild']);
  });

  it('asks once, not on every change detection', async () => {
    const runs = new FakeRuns();
    const fixture = await render(runs);

    fixture.detectChanges();
    await fixture.whenStable();

    expect(runs.asked).toEqual(['a-run']);
  });

  it('fetches the bytes rather than pointing an element at the edge', async () => {
    // An <audio src> cannot carry the Authorization header every route needs.
    const runs = new FakeRuns();
    const fixture = await render(runs);

    takes(fixture).play(TAKES.files[0]!);
    await fixture.whenStable();

    expect(runs.fetched).toEqual(['song.conservative.mp3']);
    expect(takes(fixture).playing()).toBe('song.conservative.mp3');
  });

  it('stops when the take already playing is pressed again', async () => {
    const runs = new FakeRuns();
    const fixture = await render(runs);
    takes(fixture).play(TAKES.files[0]!);
    await fixture.whenStable();

    takes(fixture).play(TAKES.files[0]!);

    expect(takes(fixture).playing()).toBeNull();
  });

  it('downloading does not start the music', async () => {
    // Pressing Download on a shared machine should not fill the room.
    const runs = new FakeRuns();
    const fixture = await render(runs);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);

    takes(fixture).save(TAKES.files[1]!);
    await fixture.whenStable();

    expect(runs.fetched).toEqual(['song.wild.mp3']);
    expect(takes(fixture).playing()).toBeNull();
    click.mockRestore();
  });

  it('tells a sleeping desktop apart from a real refusal', async () => {
    const runs = new FakeRuns();
    runs.failFileWith = new HttpErrorResponse({ status: 0 });
    const fixture = await render(runs);

    takes(fixture).play(TAKES.files[0]!);
    await fixture.whenStable();

    expect(takes(fixture).problem()).toContain('not answering');
  });
});
