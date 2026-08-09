import { TestBed } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { GOOGLE_CLIENT_ID, GoogleAuth } from './google-auth';

/** Stands in for the script Google would have loaded. */
function fakeGoogle() {
  const calls = { initialize: 0, renderButton: 0, prompt: 0, disableAutoSelect: 0 };
  let handler: ((r: { credential?: string }) => void) | undefined;
  const google = {
    accounts: {
      id: {
        initialize(config: { callback: (r: { credential?: string }) => void }) {
          calls.initialize += 1;
          handler = config.callback;
        },
        renderButton: () => void (calls.renderButton += 1),
        prompt: () => void (calls.prompt += 1),
        disableAutoSelect: () => void (calls.disableAutoSelect += 1),
      },
    },
  };
  return { google, calls, credential: (jwt: string) => handler?.({ credential: jwt }) };
}

function token(claims: object): string {
  const body = btoa(JSON.stringify(claims))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `header.${body}.sig`;
}

const CLIENT = '356639811299-example.apps.googleusercontent.com';

describe('GoogleAuth', () => {
  let fake: ReturnType<typeof fakeGoogle>;
  let auth: GoogleAuth;

  beforeEach(() => {
    fake = fakeGoogle();
    (globalThis as Record<string, unknown>)['google'] = fake.google;
    TestBed.configureTestingModule({
      providers: [{ provide: GOOGLE_CLIENT_ID, useValue: CLIENT }],
    });
    auth = TestBed.inject(GoogleAuth);
  });

  afterEach(() => delete (globalThis as Record<string, unknown>)['google']);

  it('sets the library up once however many entry points ask', async () => {
    // Google logs "initialize() is called multiple times ... only the last
    // initialized instance will be used". That warning was visible in the
    // console of the deployed site, and an earlier comment here claimed
    // calling it twice was harmless.
    await auth.mountButton(document.createElement('div'));
    await auth.signIn();
    await auth.mountButton(document.createElement('div'));

    expect(fake.calls.initialize).toBe(1);
    expect(fake.calls.renderButton).toBe(2);
    expect(fake.calls.prompt).toBe(1);
  });

  it('keeps a credential Google hands back', async () => {
    await auth.mountButton(document.createElement('div'));

    fake.credential(token({
      email: 'owner@example.invalid',
      name: 'Owner',
      exp: Math.floor(Date.now() / 1000) + 3600,
    }));

    expect(auth.user()?.email).toBe('owner@example.invalid');
    expect(auth.token()).not.toBeNull();
  });

  it('throws away a credential it cannot read', async () => {
    // Sending it would spend a request to be told 401 by a server that can
    // read it properly.
    await auth.mountButton(document.createElement('div'));

    fake.credential('not-a-jwt');

    expect(auth.user()).toBeNull();
    expect(auth.token()).toBeNull();
  });

  it('throws away one that is already spent', async () => {
    await auth.mountButton(document.createElement('div'));

    fake.credential(token({ email: 'a@b.invalid', exp: Math.floor(Date.now() / 1000) - 60 }));

    expect(auth.token()).toBeNull();
  });

  it('forgets the token on sign out, and tells Google to as well', async () => {
    await auth.mountButton(document.createElement('div'));
    fake.credential(token({ email: 'a@b.invalid', exp: Math.floor(Date.now() / 1000) + 3600 }));

    auth.signOut();

    expect(auth.user()).toBeNull();
    expect(fake.calls.disableAutoSelect).toBe(1);
  });

  describe('loading the script', () => {
    // Every test above puts a fake `google` on globalThis, so loadScript
    // returns immediately and none of this is reached. These take it away.
    let added: HTMLScriptElement[];

    beforeEach(() => {
      delete (globalThis as Record<string, unknown>)['google'];
      added = [];
      vi.spyOn(document.head, 'appendChild').mockImplementation(((
        node: HTMLScriptElement,
      ) => {
        added.push(node);
        return node;
      }) as typeof document.head.appendChild);
    });

    afterEach(() => vi.restoreAllMocks());

    it('lets a later attempt try again after one fails', async () => {
      const first = auth.mountButton(document.createElement('div'));
      added[0].onerror?.(new Event('error'));
      await expect(first).rejects.toThrow(/could not be loaded/);

      const second = auth.mountButton(document.createElement('div'));
      expect(added).toHaveLength(2);

      added[1].onerror?.(new Event('error'));
      await expect(second).rejects.toThrow(/could not be loaded/);
    });

    it('does not cache a failure that came from a tag already on the page', async () => {
      // The branch for a tag this did not add kept its rejected promise, so
      // the first failure was permanent however the script later behaved,
      // while the branch that adds one cleared it and could retry. Same
      // situation, opposite outcome, depending only on who put the tag there.
      const tag = document.createElement('script');
      tag.src = 'https://accounts.google.com/gsi/client';
      document.head.append(tag); // append, so the appendChild spy stays clean
      try {
        const first = auth.mountButton(document.createElement('div'));
        tag.dispatchEvent(new Event('error'));
        await expect(first).rejects.toThrow();

        // The same tag then succeeds, which is what a retry is for. A cached
        // rejection would refuse before ever looking.
        const second = auth.mountButton(document.createElement('div'));
        (globalThis as Record<string, unknown>)['google'] = fake.google;
        tag.dispatchEvent(new Event('load'));

        await expect(second).resolves.toBeUndefined();
        expect(fake.calls.renderButton).toBe(1);
      } finally {
        tag.remove();
      }
    });

    it('gives up rather than waiting forever', async () => {
      // A request that is dropped rather than refused fires no error event.
      // Without a bound the button says "loading" for as long as the tab is
      // open, which is the empty space this component exists to prevent.
      vi.useFakeTimers();
      try {
        const pending = auth.mountButton(document.createElement('div'));
        const settled = expect(pending).rejects.toThrow(/did not load in time/);
        await vi.advanceTimersByTimeAsync(20_000);
        await settled;
      } finally {
        vi.useRealTimers();
      }
    });
  });

  it('refuses to ask Google for anything without a client id', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [{ provide: GOOGLE_CLIENT_ID, useValue: '' }],
    });
    const unset = TestBed.inject(GoogleAuth);

    await expect(unset.mountButton(document.createElement('div'))).rejects.toThrow(
      /not configured/,
    );
    expect(fake.calls.initialize).toBe(0);
  });
});
