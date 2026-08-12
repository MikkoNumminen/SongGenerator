/**
 * Whether the refusal should stand in front of the routed page.
 *
 * A rule rather than a line in a template, because getting it wrong is silent:
 * the page it covers simply never appears, and the person it was written for
 * sees a refusal instead.
 *
 * Not on an invitation. Somebody opening one is refused by every other route
 * on the way in, which is exactly the state the invitation exists to end, so
 * covering that page would hide the one thing that would have let them in.
 */
const OPEN_TO_STRANGERS = ['/invite'];

export function standInFront(refused: boolean, url: string): boolean {
  if (!refused) {
    return false;
  }
  return !OPEN_TO_STRANGERS.some(
    (path) => url === path || url.startsWith(`${path}/`) || url.startsWith(`${path}?`),
  );
}
