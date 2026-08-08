/**
 * Settings read when the page loads, rather than baked into the build.
 *
 * Two of them differ per deployment and neither is worth a rebuild: where the
 * edge lives, and which Google client id signs people in. The backend address
 * in particular is a tunnel to a desktop and can change without anything about
 * this application changing.
 *
 * None of this is secret and it cannot be. The browser has to know where to
 * send requests, so the address is visible in the shipped files however it
 * gets there. Keeping it out of the repository is worth doing because it stops
 * a home machine's address living in git history forever, but it is tidiness
 * rather than security. What actually protects the service is that the edge
 * checks every request against an allowlist.
 */
export interface RuntimeConfig {
  /** Base URL of the edge, no trailing slash. */
  readonly apiBaseUrl: string;
  /** Google OAuth client id, or '' when sign-in is not set up. */
  readonly googleClientId: string;
}

/** Where the edge listens when it is running on the same machine as the page. */
export const LOCAL_BACKEND = 'http://127.0.0.1:8000';

/**
 * What to use when there is no config file, or it is unreadable.
 *
 * No address at all. This used to default to the local backend, which is
 * right when you are sitting at the machine and indefensible anywhere else: a
 * public page asking for `http://127.0.0.1:8000` is a website reaching into
 * the visitor's own computer. Chrome now asks the visitor to allow "access to
 * other apps and services on this device", which is exactly the question it
 * should ask and exactly the impression no honest site wants to make. It could
 * not have worked either way, since an HTTPS page may not call HTTP.
 *
 * So the local default is applied only when the page is itself being served
 * locally. See `defaultApiBaseUrl`.
 */
export const DEFAULT_CONFIG: RuntimeConfig = {
  apiBaseUrl: '',
  googleClientId: '',
};

/** Whether the page itself came from this machine. */
function servedLocally(hostname: string): boolean {
  return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]';
}

/**
 * The address to assume when the config file says nothing.
 *
 * Localhost while developing, because that is convenient and harmless when the
 * page and the backend are the same machine. Nothing at all once deployed,
 * because guessing there means probing a stranger's computer.
 */
export function defaultApiBaseUrl(hostname: string): string {
  return servedLocally(hostname) ? LOCAL_BACKEND : DEFAULT_CONFIG.apiBaseUrl;
}

function text(source: Record<string, unknown>, key: string): string | undefined {
  const value = source[key];
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : undefined;
}

/**
 * Turn whatever was fetched into settings, keeping the defaults for anything
 * missing or the wrong shape.
 *
 * Deliberately total: there is no input this rejects. A config file with a
 * typo in it must not stop the application booting, because then nobody can
 * even see the message explaining what is wrong.
 */
export function readRuntimeConfig(
  raw: unknown,
  hostname: string = typeof location === 'undefined' ? '' : location.hostname,
): RuntimeConfig {
  const fallback = defaultApiBaseUrl(hostname);
  if (!raw || typeof raw !== 'object') {
    return { ...DEFAULT_CONFIG, apiBaseUrl: fallback };
  }
  const source = raw as Record<string, unknown>;
  const base = text(source, 'apiBaseUrl') ?? fallback;
  return {
    // A trailing slash would produce `//health`, which some servers answer and
    // others do not. Cheaper to fix here than to debug once deployed.
    apiBaseUrl: base.replace(/\/+$/, ''),
    googleClientId: text(source, 'googleClientId') ?? DEFAULT_CONFIG.googleClientId,
  };
}

/**
 * Fetch the config file. Never rejects.
 *
 * Bootstrapping must not depend on this succeeding: a missing file, a 404 page
 * served as HTML, or no network at all should all leave a usable application
 * that says the machine is not answering.
 */
export async function loadRuntimeConfig(
  url = 'config.json',
  fetcher: typeof fetch = fetch,
  hostname: string = typeof location === 'undefined' ? '' : location.hostname,
): Promise<RuntimeConfig> {
  const empty = { ...DEFAULT_CONFIG, apiBaseUrl: defaultApiBaseUrl(hostname) };
  try {
    const response = await fetcher(url, { cache: 'no-store' });
    if (!response.ok) {
      return empty;
    }
    return readRuntimeConfig(await response.json(), hostname);
  } catch {
    return empty;
  }
}
