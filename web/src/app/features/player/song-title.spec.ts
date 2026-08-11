import { describe, expect, it } from 'vitest';

import { prettySongTitle } from './song-title';

describe('reading a folder name as a title', () => {
  it('splits the artist from the song', () => {
    expect(prettySongTitle('chisu_-_sabotage_official_video')).toBe(
      'Chisu · Sabotage',
    );
  });

  it('strips what a video site appended', () => {
    expect(
      prettySongTitle('jenni_vartiainen_-_missä_muruseni_on_official_music_video'),
    ).toBe('Jenni Vartiainen · Missä Muruseni on');
  });

  it('stops stripping at the first word that is not noise', () => {
    // "universe" is part of the title and "lyrics in subs" is not. Removing
    // noise wherever it appeared would take "in" out of the middle too.
    expect(
      prettySongTitle('ayreon_-_dawn_of_a_million_souls_universe_lyrics_in_subs'),
    ).toBe('Ayreon · Dawn of a Million Souls Universe');
  });

  it('keeps a noise word that is part of the name', () => {
    // Only the end is stripped, so the leading "music" survives.
    expect(prettySongTitle('music_sdp')).toBe('Music Sdp');
  });

  it('splits camelCase before lowercasing it away', () => {
    expect(prettySongTitle('musicHyvaVenaj')).toBe('Music Hyva Venaj');
  });

  it('leaves a name that is already plain alone', () => {
    expect(prettySongTitle('kalasatamaan')).toBe('Kalasatamaan');
    expect(prettySongTitle('baarikärpänen')).toBe('Baarikärpänen');
  });

  it('keeps hyphens that mean something', () => {
    expect(prettySongTitle('mokoma_-_takatalvi_re-recorded_2018')).toBe(
      'Mokoma · Takatalvi Re-recorded 2018',
    );
    expect(prettySongTitle('sanni_-_2080-luvulla')).toBe('Sanni · 2080-luvulla');
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
