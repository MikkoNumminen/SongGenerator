import { describe, expect, it } from 'vitest';

import {
  DEFAULT_CONFIG,
  LOCAL_BACKEND,
  loadRuntimeConfig,
  readRuntimeConfig,
} from './runtime-config';

const response = (body: unknown, ok = true): Response =>
  ({ ok, json: () => Promise.resolve(body) }) as Response;

describe('reading the deployment settings', () => {
  it('takes both values when they are there', () => {
    expect(
      readRuntimeConfig({
        apiBaseUrl: 'https://desk.example.invalid',
        googleClientId: 'abc.apps.googleusercontent.com',
      }),
    ).toEqual({
      apiBaseUrl: 'https://desk.example.invalid',
      googleClientId: 'abc.apps.googleusercontent.com',
    });
  });

  it('drops a trailing slash', () => {
    // Otherwise every URL is joined into `//health`, which some servers answer
    // and others do not: cheaper to fix here than to debug once deployed.
    expect(readRuntimeConfig({ apiBaseUrl: 'https://desk.invalid/' }).apiBaseUrl)
      .toBe('https://desk.invalid');
  });

  it.each([
    ['nothing at all', undefined],
    ['null', null],
    ['a string', 'not a config'],
    ['an array', []],
    ['an empty object', {}],
    ['the wrong types', { apiBaseUrl: 42, googleClientId: false }],
    ['blank values', { apiBaseUrl: '   ', googleClientId: '' }],
  ])('falls back to the defaults for %s', (_why, input) => {
    // Nothing here may reject. A typo in a config file must not stop the app
    // booting, because then nobody can see the message explaining what broke.
    // The hostname is given rather than taken from the test environment, so
    // what this asserts does not change with where the runner thinks it is.
    expect(readRuntimeConfig(input, 'songgen.example.invalid')).toEqual(DEFAULT_CONFIG);
  });

  it('keeps whichever half is usable', () => {
    const config = readRuntimeConfig({ apiBaseUrl: 'https://desk.invalid' });

    expect(config.apiBaseUrl).toBe('https://desk.invalid');
    expect(config.googleClientId).toBe('');
  });
});

describe('fetching them', () => {
  it('uses the file when it is there', async () => {
    const fetcher = () => Promise.resolve(response({ apiBaseUrl: 'https://a.invalid' }));

    expect((await loadRuntimeConfig('config.json', fetcher as typeof fetch)).apiBaseUrl)
      .toBe('https://a.invalid');
  });

  it.each([
    ['the file is missing', () => Promise.resolve(response('<html>404</html>', false))],
    ['the network is gone', () => Promise.reject(new Error('offline'))],
    ['the body is not JSON', () => Promise.resolve({
      ok: true, json: () => Promise.reject(new SyntaxError('unexpected <')),
    } as unknown as Response)],
  ])('still boots when %s', async (_why, fetcher) => {
    // A deployment that failed to write its config still produces a running
    // application, which then says plainly that it was never told where its
    // backend is.
    await expect(
      loadRuntimeConfig('config.json', fetcher as typeof fetch, 'songgen.example.invalid'),
    ).resolves.toEqual(DEFAULT_CONFIG);
  });

  it('asks for a fresh copy rather than a cached one', async () => {
    // The address of the machine is exactly the thing that changes, and a
    // stale cached config points a redeployed site at an old tunnel.
    let seen: RequestInit | undefined;
    const fetcher = (_url: string, init?: RequestInit) => {
      seen = init;
      return Promise.resolve(response({}));
    };

    await loadRuntimeConfig('config.json', fetcher as unknown as typeof fetch);

    expect(seen?.cache).toBe('no-store');
  });
});

describe('never guessing an address once deployed', () => {
  it('assumes the local backend only when the page is itself local', () => {
    // Convenient and harmless when the page and the edge are one machine.
    for (const host of ['localhost', '127.0.0.1', '[::1]']) {
      expect(readRuntimeConfig({}, host).apiBaseUrl).toBe(LOCAL_BACKEND);
    }
  });

  it('assumes nothing at all on a real hostname', () => {
    // A public page asking for http://127.0.0.1:8000 is a website reaching
    // into the visitor's own computer. Chrome prompts about exactly that, and
    // being the site that triggers the prompt is worse than admitting the
    // deployment is unfinished. It could not have worked anyway: an HTTPS page
    // may not call HTTP.
    expect(readRuntimeConfig({}, 'green-bay-0f4fe1d03.7.azurestaticapps.net').apiBaseUrl)
      .toBe('');
    expect(readRuntimeConfig(undefined, 'example.invalid').apiBaseUrl).toBe('');
  });

  it('still takes a configured address on any host', () => {
    expect(readRuntimeConfig({ apiBaseUrl: 'https://desk.invalid' }, 'anywhere.invalid')
      .apiBaseUrl).toBe('https://desk.invalid');
  });

  it('guesses nothing when the fetch fails on a deployed host', async () => {
    const dead = () => Promise.reject(new Error('offline'));

    const config = await loadRuntimeConfig('config.json', dead as typeof fetch,
                                           'songgen.example.invalid');

    expect(config.apiBaseUrl).toBe('');
  });
});
