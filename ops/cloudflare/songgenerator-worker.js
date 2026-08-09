// Serves the Static Web App at mikkonumminen.dev/songGenerator.
//
// Deploy as a Cloudflare Worker with a route of `mikkonumminen.dev/songGenerator*`
// on the free plan. Nothing else on the domain is affected: a request that does
// not start with the prefix is passed straight through.
//
// The prefix is stripped before the request reaches Azure. Azure serves the app
// from the root of its own hostname and knows nothing about this path, so
// forwarding `/songGenerator/main.js` unchanged would miss every file and the
// site's own fallback would answer with index.html: a page that loads and then
// fails to run, which reads as a blank screen.
//
// The app is built with `--base-href /songGenerator/` to match, so the browser
// asks for the prefixed paths this then removes. The two have to agree; change
// one and the other stops working.

const PREFIX = '/songGenerator';
const ORIGIN = 'green-bay-0f4fe1d03.7.azurestaticapps.net';

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (!url.pathname.startsWith(PREFIX)) {
      return fetch(request);
    }

    // Without the trailing slash the browser resolves every relative URL
    // against the parent, so redirect once rather than serve a broken page.
    if (url.pathname === PREFIX) {
      return Response.redirect(`${url.origin}${PREFIX}/${url.search}`, 301);
    }

    const target = new URL(url);
    target.hostname = ORIGIN;
    target.protocol = 'https:';
    target.port = '';
    target.pathname = url.pathname.slice(PREFIX.length) || '/';

    // The Host header has to follow the URL, or Azure answers for a site it
    // does not have and returns its own 404.
    const forwarded = new Request(target, request);
    forwarded.headers.set('Host', ORIGIN);
    return fetch(forwarded);
  },
};
