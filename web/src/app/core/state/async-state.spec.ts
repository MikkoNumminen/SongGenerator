import { describe, expect, it } from 'vitest';

import {
  AsyncState,
  empty,
  failed,
  idle,
  loading,
  offline,
  ready,
  valueOf,
} from './async-state';

describe('AsyncState', () => {
  const everyState: AsyncState<string>[] = [
    idle(),
    loading(),
    empty(),
    offline(),
    failed('nope'),
    ready('a song'),
  ];

  it('is exactly one thing at a time', () => {
    // The reason this is a union rather than a pair of booleans: a view
    // holding `loading` and `data` separately can be in combinations nobody
    // designed, and those render as a blank screen.
    expect(new Set(everyState.map((s) => s.kind)).size).toBe(everyState.length);
  });

  it('carries a value only when it is ready', () => {
    for (const state of everyState) {
      expect(valueOf(state)).toBe(state.kind === 'ready' ? 'a song' : undefined);
    }
  });

  it('does not throw when a template asks the wrong state for its value', () => {
    // A template bug should render an incomplete page, not blow up during
    // rendering and leave a blank one.
    expect(() => valueOf(offline())).not.toThrow();
  });

  it('keeps offline and error apart', () => {
    // The whole reason this file exists. The backend is a desktop that is
    // often switched off, which is normal here and is not a fault.
    expect(offline().kind).not.toBe(failed('x').kind);
  });

  it('keeps a message with an error, because a bare "error" says nothing', () => {
    const state = failed('the bank has no clips built yet');

    expect(state).toEqual({
      kind: 'error',
      message: 'the bank has no clips built yet',
    });
  });

  it('lets a value be falsy without looking absent', () => {
    // `valueOf` returning undefined must mean "no value", not "a value that
    // happens to be 0 or empty", or a caller checking truthiness reads a real
    // answer as a missing one.
    expect(valueOf(ready(0))).toBe(0);
    expect(valueOf(ready(''))).toBe('');
  });
});
