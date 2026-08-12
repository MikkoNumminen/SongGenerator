/**
 * Turn a folder name on that desktop into something readable.
 *
 * The songs are named by whatever they were downloaded as, so the library is
 * a wall of `avantasia_-_ghostlights_official_track_lyrics`. That is the name
 * the machine uses and it has to stay reachable, but it is not what a person
 * reads a list of thirty by.
 *
 * The cleaning is deliberately timid. It only removes words from the end,
 * because that is where the noise a video site adds lives, and a word that
 * looks like noise in the middle is usually part of the title: `music_sdp`
 * keeps its `music`, and `Dawn of a Million Souls Universe` keeps `Universe`
 * because the stripping stops at the first word that is not noise.
 */

/** Words a video site appends. Only ever removed from the end of a name. */
const NOISE = new Set([
  'official', 'video', 'lyric', 'lyrics', 'track', 'audio', 'music', 'hd',
  '4k', 'full', 'version', 'in', 'subs', 'visualizer', 'mv', 'remastered',
]);

/** Kept lowercase inside a title, the way titles are actually set. */
const SMALL = new Set([
  'of', 'a', 'the', 'and', 'in', 'on', 'to', 'for', 'with', 'at', 'ja',
]);

export function prettySongTitle(slug: string): string {
  // camelCase before anything else: `musicHyvaVenaj` is three words, and
  // lowercasing first would lose the only evidence of where they split.
  const spaced = slug
    .replace(/([a-zäöå0-9])([A-ZÄÖÅ])/g, '$1 $2')
    .replace(/_-_/g, ' · ')
    .replace(/_/g, ' ')
    .trim();

  const words = spaced.split(/\s+/);
  // Never strip down to nothing: a song actually called "official video"
  // would otherwise end up with no name at all.
  while (words.length > 1 && NOISE.has(words[words.length - 1]!.toLowerCase())) {
    words.pop();
  }

  const cleaned = words.join(' ').replace(/[\s·\-]+$/, '');
  if (!cleaned) {
    return slug;
  }

  return cleaned
    .split(' ')
    .map((word, i) => {
      const low = word.toLowerCase();
      if (i > 0 && SMALL.has(low)) {
        return low;
      }
      return low.charAt(0).toUpperCase() + low.slice(1);
    })
    .join(' ');
}
