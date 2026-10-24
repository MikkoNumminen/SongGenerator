import { describe, expect, it } from 'vitest';

import { prettySongTitle } from './song-title';

describe('reading a folder name as a title', () => {
  it('splits the artist from the song', () => {
    expect(prettySongTitle('artisti_-_kappale_official_video')).toBe(
      'Artisti · Kappale',
    );
  });

  it('strips what a video site appended', () => {
    expect(
      prettySongTitle('eka_laulaja_-_kesä_tulee_official_music_video'),
    ).toBe('Eka Laulaja · Kesä Tulee');
  });

  it('stops stripping at the first word that is not noise', () => {
    // "universe" is part of the title and "lyrics in subs" is not. Removing
    // noise wherever it appeared would take "in" out of the middle too.
    expect(
      prettySongTitle('yhtye_-_songs_of_a_quiet_universe_lyrics_in_subs'),
    ).toBe('Yhtye · Songs of a Quiet Universe');
  });

  it('keeps a noise word that is part of the name', () => {
    // Only the end is stripped, so the leading "music" survives.
    expect(prettySongTitle('music_box')).toBe('Music Box');
  });

  it('splits camelCase before lowercasing it away', () => {
    expect(prettySongTitle('musicKesaYo')).toBe('Music Kesa Yo');
  });

  it('leaves a name that is already plain alone', () => {
    expect(prettySongTitle('iltalaulu')).toBe('Iltalaulu');
    expect(prettySongTitle('kesäpäivä')).toBe('Kesäpäivä');
  });

  it('keeps hyphens that mean something', () => {
    expect(prettySongTitle('yhtye_-_kevät_re-recorded_1999')).toBe(
      'Yhtye · Kevät Re-recorded 1999',
    );
    expect(prettySongTitle('laulaja_-_ilta-aurinko')).toBe('Laulaja · Ilta-aurinko');
  });

  it('never strips a name down to nothing', () => {
    // Every word is noise. Stripping to the last one beats an empty heading.
    expect(prettySongTitle('official_video')).toBe('Official');
  });

  it('falls back to the folder name rather than returning nothing', () => {
    expect(prettySongTitle('')).toBe('');
    expect(prettySongTitle('_')).toBe('_');
  });
});
