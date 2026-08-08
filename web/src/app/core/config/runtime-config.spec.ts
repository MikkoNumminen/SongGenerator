import { describe, expect, it } from 'vitest';

import { DEFAULT_CONFIG, loadRuntimeConfig, readRuntimeConfig } from './runtime-config';

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
    expect(readRuntimeConfig(input)).toEqual(DEFAULT_CONFIG);
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
    // A deployment that failed to write its config then looks exactly like a
    // switched-off desktop, which this application renders honestly.
    await expect(loadRuntimeConfig('config.json', fetcher as typeof fetch))
      .resolves.toEqual(DEFAULT_CONFIG);
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
