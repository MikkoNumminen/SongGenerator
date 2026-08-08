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

/**
 * What to use when there is no config file, or it is unreadable.
 *
 * The local backend, because that is what somebody running this from a clone
 * is pointing at. A deployment that fails to write its config therefore looks
 * exactly like a switched-off desktop, which is a state this application
 * already renders honestly, instead of a blank page or a crash on boot.
 */
export const DEFAULT_CONFIG: RuntimeConfig = {
  apiBaseUrl: 'http://127.0.0.1:8000',
  googleClientId: '',
};

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
export function readRuntimeConfig(raw: unknown): RuntimeConfig {
  if (!raw || typeof raw !== 'object') {
    return DEFAULT_CONFIG;
  }
  const source = raw as Record<string, unknown>;
  const base = text(source, 'apiBaseUrl') ?? DEFAULT_CONFIG.apiBaseUrl;
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
): Promise<RuntimeConfig> {
  try {
    const response = await fetcher(url, { cache: 'no-store' });
    if (!response.ok) {
      return DEFAULT_CONFIG;
    }
    return readRuntimeConfig(await response.json());
  } catch {
    return DEFAULT_CONFIG;
  }
}
