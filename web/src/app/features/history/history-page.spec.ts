import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Observable, of } from 'rxjs';
import { describe, expect, it } from 'vitest';

import { API_BASE_URL } from '../../core/api/api-config';
import { HistoryReply, JobReply } from '../../core/contract/dto';
import { RUN_SOURCE, RunSource } from '../../core/ports/run-source.port';
import { fakeAuth } from '../../core/auth/fake-auth';
import { HistoryPage } from './history-page';

function run(id: string, stage: string): JobReply {
  return {
    id,
    stage,
    // What the edge reports: refused and failed are settled too, which is
    // exactly the distinction these tests are about.
    settled: ['done', 'refused', 'failed'].includes(stage),
    created_at: '2026-08-12T09:00:00+00:00',
    requested_by: 'someone@example.com',
    source_url: 'https://example.invalid/song',
    bank: 'ppbank',
    song: `song-${id}`,
  };
}

const RUNS = [run('a', 'done'), run('b', 'failed'), run('c', 'refused')];

class FakeRuns implements Partial<RunSource> {
  asked = 0;

  history(): Observable<HistoryReply> {
    this.asked += 1;
    return of({ jobs: RUNS });
  }

  files(): Observable<never> {
    throw new Error('the takes box must not be reachable for these runs');
  }
}

async function render(runs: FakeRuns): Promise<ComponentFixture<HistoryPage>> {
  TestBed.configureTestingModule({
    imports: [HistoryPage],
    providers: [
      provideRouter([]),
      fakeAuth().provider,
      { provide: RUN_SOURCE, useValue: runs },
      { provide: API_BASE_URL, useValue: 'https://edge.invalid' },
    ],
  });
  const fixture = TestBed.createComponent(HistoryPage);
  fixture.detectChanges();
  await fixture.whenStable();
  fixture.detectChanges();
  return fixture;
}

function openers(fixture: ComponentFixture<HistoryPage>): HTMLButtonElement[] {
  return Array.from(
    fixture.nativeElement.querySelectorAll('.opener button'),
  ) as HTMLButtonElement[];
}

describe('earlier runs', () => {
  it('reads what was run before', async () => {
    const runs = new FakeRuns();

    const fixture = await render(runs);

    expect(runs.asked).toBe(1);
    expect(fixture.componentInstance.rows().length).toBe(3);
  });

  it('offers the takes only on a run that produced some', async () => {
    // Settled covers refused and failed as well, and neither wrote a file.
    // Those rows opened onto an empty box, which reads as one still loading.
    const fixture = await render(new FakeRuns());

    expect(openers(fixture).length).toBe(1);
  });

  it('opens one run at a time, and closes the one already open', async () => {
    const fixture = await render(new FakeRuns());
    const page = fixture.componentInstance;

    page.toggle('a');
    expect(page.openRun()).toBe('a');
    page.toggle('a');
    expect(page.openRun()).toBeNull();
  });
});
