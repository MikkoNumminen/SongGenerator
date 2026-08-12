import { describe, expect, it } from 'vitest';

import { standInFront } from './stand-in-front';

describe('whether the refusal covers the page', () => {
  it('covers an ordinary page for somebody who was refused', () => {
    expect(standInFront(true, '/songs')).toBe(true);
    expect(standInFront(true, '/')).toBe(true);
  });

  it('never covers anything for somebody who was not', () => {
    expect(standInFront(false, '/songs')).toBe(false);
  });

  it('steps aside for an invitation', () => {
    // Somebody opening one is refused by every other route on the way in,
    // which is the state the invitation exists to end. Covering it would hide
    // the one page that would have let them in.
    expect(standInFront(true, '/invite/a-token')).toBe(false);
  });

  it('steps aside for an invitation carrying a query', () => {
    expect(standInFront(true, '/invite/a-token?from=mail')).toBe(false);
  });

  it('is not fooled by a page that merely starts with the same letters', () => {
    expect(standInFront(true, '/invited-guests')).toBe(true);
  });
});
