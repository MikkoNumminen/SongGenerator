import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { ThemeSwitch } from './theme';

const STORAGE_KEY = 'songgen.theme';

describe('ThemeSwitch', () => {
  beforeEach(() => {
    localStorage.removeItem(STORAGE_KEY);
    document.documentElement.removeAttribute('data-theme');
    TestBed.configureTestingModule({});
  });

  afterEach(() => {
    localStorage.removeItem(STORAGE_KEY);
    document.documentElement.removeAttribute('data-theme');
  });

  it('writes no attribute until somebody chooses', () => {
    const themes = TestBed.inject(ThemeSwitch);

    // The stylesheet's own `prefers-color-scheme` block is correct on its own,
    // and stamping an attribute over it would freeze the page on whatever the
    // machine happened to say at boot.
    expect(themes.preference()).toBe('system');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('remembers a choice and tells the stylesheet about it', () => {
    const themes = TestBed.inject(ThemeSwitch);

    themes.choose('dark');

    expect(themes.theme()).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem(STORAGE_KEY)).toBe('dark');
  });

  it('starts from what was chosen last time', () => {
    localStorage.setItem(STORAGE_KEY, 'light');

    const themes = TestBed.inject(ThemeSwitch);

    expect(themes.preference()).toBe('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  it('toggles to the other one, which means leaving system behind', () => {
    const themes = TestBed.inject(ThemeSwitch);
    themes.choose('light');

    themes.toggle();

    expect(themes.preference()).toBe('dark');
    expect(themes.theme()).toBe('dark');
  });

  it('goes back to following the machine, and stops storing an answer', () => {
    const themes = TestBed.inject(ThemeSwitch);
    themes.choose('dark');

    themes.choose('system');

    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});
