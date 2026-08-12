import { Subject, of, throwError } from 'rxjs';
import { describe, expect, it, vi } from 'vitest';

import { Kept } from './kept';

describe('an answer fetched once', () => {
  it('asks once however many times it is read', () => {
    const fetch = vi.fn(() => of('the library'));
    const kept = new Kept(fetch);

    kept.get().subscribe();
    kept.get().subscribe();
    kept.get().subscribe();

    expect(fetch).toHaveBeenCalledOnce();
  });

  it('answers a later reader without asking again', () => {
    // This is what makes a second visit to a page draw immediately rather
    // than flashing its loading state.
    const kept = new Kept(() => of('the library'));
    kept.get().subscribe();

    let seen: string | undefined;
    kept.get().subscribe((value) => (seen = value));

    expect(seen).toBe('the library');
  });

  it('joins a request already in flight rather than starting a second', () => {
    const answers = new Subject<string>();
    const fetch = vi.fn(() => answers.asObservable());
    const kept = new Kept(fetch);
    const seen: string[] = [];

    kept.get().subscribe((v) => seen.push(v));
    kept.get().subscribe((v) => seen.push(v));
    answers.next('one fetch');
    answers.complete();

    expect(fetch).toHaveBeenCalledOnce();
    expect(seen).toEqual(['one fetch', 'one fetch']);
  });

  it('does not keep a refusal as the answer', () => {
    // A cached failure would be handed to every later caller, so the page
    // that recovers would have nothing to recover to.
    let attempts = 0;
    const kept = new Kept(() => {
      attempts += 1;
      return attempts === 1 ? throwError(() => new Error('no')) : of('later');
    });

    kept.get().subscribe({ error: () => undefined });
    let seen: string | undefined;
    kept.get().subscribe((v) => (seen = v));

    expect(attempts).toBe(2);
    expect(seen).toBe('later');
  });

  it('fetches again after being told to forget', () => {
    const fetch = vi.fn(() => of('the library'));
    const kept = new Kept(fetch);
    kept.get().subscribe();

    kept.forget();
    kept.get().subscribe();

    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('says whether it has an answer, so a caller can skip its wait', () => {
    const kept = new Kept(() => of('the library'));
    expect(kept.ready).toBe(false);

    kept.get().subscribe();

    expect(kept.ready).toBe(true);
    kept.forget();
    expect(kept.ready).toBe(false);
  });
});
