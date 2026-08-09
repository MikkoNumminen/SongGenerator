# Running this on the homelab

Two moving parts, both switched by one toggle.

The site is static and lives on Azure. The edge is a Windows process on this
machine, because the pipeline needs the GPU, and it is reachable from the
internet through Tailscale Funnel.

## The toggle

`homelab-songgenerator.service` is a systemd user unit inside WSL, discovered by
`homelab-control` like the other three services. Turning it on starts the edge
and opens its funnel; turning it off stops both. There is no state where the
service is down and the address still answers, which is the point.

Install it once:

```bash
cp /mnt/d/koodaamista/LuokkaretkiGenerator/ops/homelab-songgenerator.service \
   ~/.config/systemd/user/
cp /mnt/d/koodaamista/LuokkaretkiGenerator/ops/songgenerator.env.example \
   ~/.config/songgenerator.env      # then edit it
systemctl --user daemon-reload
systemctl --user start homelab-songgenerator.service
systemctl --user status homelab-songgenerator.service
```

If it starts and stops cleanly it is onboarded, and the control panel lists it.

## Why the unit runs a Windows executable

Unlike the other three, `ExecStart` points at `python.exe` under `/mnt/d`, run
over WSL interop. The pipeline needs the GPU and the Windows venv torch is
installed into, so the process has to be a Windows one. It is the same trick
`ragctl` already uses to drive `tailscale.exe`.

That systemd supervises it properly was measured rather than assumed. A probe
unit reported `active`, the Windows process wrote to journald, and after
`systemctl --user stop` no Windows process was left behind.

## The interop trap

A Windows process launched from WSL does **not** inherit the unit's environment.
WSL only carries variables named in `WSLENV`, and nothing warns you when one is
missing: the service starts, `/health` answers `ok`, and the edge quietly has no
client id and no allowlist. It fails closed, so nobody gets in, but it looks
healthy while being unusable.

The unit therefore lists every variable twice, once in the env file and once in
`WSLENV`. Adding a setting means editing both.

Measured, not guessed: a plain variable arrives as `None` on the Windows side,
and the same variable with `WSLENV` naming it arrives intact.

The other thing systemd will not accept is a backslash-escaped space in an
executable path. `/mnt/c/Program\ Files/...` is refused outright with
"Executable path contains special characters"; the path has to be quoted.

## The site looks broken from this machine, and only from this machine

Opened here, the site reports "that machine is not answering" while `curl` to
the same address returns in 20 ms. Both are correct.

MagicDNS resolves `paskamyrsky.tail6ed53b.ts.net` to `100.101.51.19`, the
node's own tailnet address, for anything on the tailnet. Chrome then sees a
page served from a public site asking for something on a private network and
refuses. It is the same protection that produced the "access other apps and
services on this device" prompt earlier, and it is right to.

Everywhere else the name resolves to Tailscale's public ingress and the request
is one public host calling another, which nothing objects to. That was checked
from outside the tailnet rather than assumed: `/health` fetched from an
unrelated network returns `{"status":"ok","auth_configured":true,"busy":false}`.

So the site works for everyone except the person most likely to be testing it.
To see it as a visitor does, open it on a phone with wifi off, or from any
machine not signed in to the tailnet. `curl` from here is not a substitute: it
has no private-network policy and will happily succeed while a browser refuses.

If this becomes tiresome, the fix is to stop using a tailnet name for the
backend: a Cloudflare tunnel to a real hostname makes it public everywhere,
including here.

## Ports, and the ones not to touch

| what | where |
|---|---|
| this edge | `127.0.0.1:8020` |
| this funnel | `:10000` |
| RAG chat | `:443` → `127.0.0.1:8000` |
| oauth2-proxy | `:8443` → `127.0.0.1:4180` |

Funnel offers exactly three ports and two were already taken, so this one has
10000. 8000 was taken as well, hence 8020.

**The funnel is shared infrastructure.** `tailscale funnel reset`, or a blanket
`off`, tears down the RAG chat and the proxy along with this. The unit therefore
names its port in every command it runs and touches nothing else. Anything added
here later must do the same.

`tailscale funnel status` lists every project's routes together, so "a funnel is
on" never means this one is.

## Where the public address goes

The edge answers at `https://paskamyrsky.tail6ed53b.ts.net:10000`. That is the
value of `API_BASE_URL` for the site, and it is the one thing that changes if
the node is renamed or the port moves.

Google needs nothing when it changes. The origin registered with the OAuth
client is the *site's* origin, not the backend's.
