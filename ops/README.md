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
