# What runs in Azure, and what deliberately does not

The brief named Angular, Azure Functions, PostgreSQL, Azure DevOps and Bicep,
with one condition attached: **where alignment would mean paying for
something, do not align.**

Three of those are used. Two are not, and this file exists because "we skipped
it" is worth nothing without the reason, while a decision with a measurement
behind it is worth reading.

Nothing here costs anything. That is checked rather than assumed: the figures
below come from the current build and from Microsoft's own quota pages.

## Used

### Azure Static Web Apps, Free plan

Hosts the Angular front end.

| | |
|---|---|
| price | free, and overage is *unavailable* rather than billed |
| bandwidth | 100 GB a month, subscription-wide |
| a first visit here | ~104 kB compressed |
| so | roughly a million first visits a month |
| app size limit | 250 MB per environment against a 338 kB build |
| apps per subscription | 10 on Free |

The overage rule is the interesting one. Exceed the allowance and the site
stops being served; it never turns into a bill. The zero-cost constraint is
enforced by the platform rather than by watching a dashboard.

### Azure Bicep

`infra/main.bicep` declares the resource group and the site, at subscription
scope so one command creates both and so `what-if` works against a
subscription that has neither yet.

### What `what-if` reports and you can ignore

Against an existing site it says three properties would be cleared:

    properties.provider           'SwaCli' -> None
    properties.stableInboundIP    '9.163...' -> None
    properties.trafficSplitting   {...} -> None

None of them are declared here and none should be. `provider` records what
published last, `stableInboundIP` is assigned by Azure, and `trafficSplitting`
is the default share between environments. `what-if` lists every property the
template does not mention as though it were being removed, and an incremental
deployment leaves them alone.

`deploymentAuthPolicy` used to appear in that list too and no longer does. It
decides whether a deployment token may publish at all, which is precisely how
the pipeline works, so it is stated rather than inherited. It was correct
already; nothing said so, and a diff threatening to clear it is a poor moment
to learn what it does.

The deployment token is deliberately **not** an output. Outputs are kept in the
deployment history and readable by anyone with access to the group, and that
token alone is enough to publish to the site. The pipeline fetches it at run
time.

### Azure DevOps Pipelines, and why it is not used any more

`azure-pipelines.yml` built, tested and published the site until 2026-08-11.
It is still in the repository, with its trigger off, because the Azure version
of this deployment is worth reading next to the one that replaced it.

What went wrong was not the YAML. The pipeline simply stopped producing runs,
and nothing in the repository could see that: a front end was rewritten,
reviewed and merged with a green suite and a clean build, and the site went on
serving a build two days old. The theory at the time was the trigger's path
filter, `web/*`, which is genuinely ambiguous in Azure's own documentation. It
was corrected, and correcting it edited this file, which was the one trigger
that had always worked, and still nothing ran.

The likeliest cause is the caveat that was already written down here: Microsoft
no longer grants hosted parallelism automatically, and a build with no grant
sits queued rather than failing, which looks exactly like no trigger at all.
That cannot be confirmed from the repository. It needs the run list at
`dev.azure.com`, and getting to it means a personal Microsoft account that the
Azure Portal's tenant picker refuses, which `docs/WORKFLOWS.md` records
happening before.

**So the publisher moved to `.github/workflows/deploy.yml`.** This repository
is public, GitHub Actions is unmetered on standard runners for public
repositories, and it needs no grant request and no second console. It does the
same work with the same deployment token, and it ends by asking the site what
it is serving, which is the check whose absence let all of this happen quietly.

Nothing else about the Azure side changed. The site is a Static Web App, made
by Bicep, and free.

## Not used

### Azure Functions

**The work needs a GPU.** Separation is Demucs or Mel-Band Roformer, pitch
extraction is torchcrepe, and resynthesis is WORLD. A render holds about
3.5 GB and takes minutes. Functions cannot host that on any plan, and cloud GPU
is excluded by the brief's own rule.

The FastAPI edge in `api/` is small enough to be a Function, and that was
considered. It would be worse: the edge starts pipeline processes, reads stems
from `work/`, and writes renders to `output/`, all on the machine with the
card. Moving it to Azure would leave it calling back to that same desktop for
everything, adding a hop and a second thing to deploy while removing nothing.

What it would buy is a public address without a tunnel. That is real, and it is
not worth an architecture built around a machine the code cannot reach.

### PostgreSQL

**The job history has to live where the runs happen.** It is a table of
processes on one machine, reconciled at startup against what that machine was
doing when it was last shut down. A database in another country cannot answer
"was this run still going when the power went out".

It is also the wrong size. One desktop takes one run at a time, so the write
rate is a handful of rows a minute, and SQLite in WAL mode beside the pipeline
is a better fit than a managed server. Azure Database for PostgreSQL has an
introductory free period and charges afterwards, which fails the rule outright.

If this ever became a service with several machines and several people, the
job table is exactly the thing that would move. It is behind `JobStore` for
that reason, so the change would be one class rather than a rewrite.

## What is where

| piece | runs on | why |
|---|---|---|
| Angular front end | Azure Static Web Apps | static files, free, global |
| building and publishing it | GitHub Actions | unmetered for a public repository, and next to the code |
| FastAPI edge | the desktop | starts runs, reads and writes their files |
| audio pipeline | the desktop | needs the GPU |
| job history | SQLite on the desktop | must match the processes it describes |
| rendered songs | the desktop | 14 files a song; a single mp3 is 69 times a page load |

That last row is also why serving audio from Azure would be a mistake even
though it is the obvious place to put files. One song's renders are around
100 MB. The quota that comfortably carries a million page views carries a
thousand songs, and the files are already sitting on the machine that made
them.
