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

The deployment token is deliberately **not** an output. Outputs are kept in the
deployment history and readable by anyone with access to the group, and that
token alone is enough to publish to the site. The pipeline fetches it at run
time.

### Azure DevOps Pipelines

`azure-pipelines.yml` builds, tests and publishes. It runs only when `web/` or
the pipeline itself changed: the audio pipeline is most of this repository and
cannot affect what gets published, so building it would spend the free minutes
on nothing.

One caveat that is friction rather than cost: Microsoft no longer grants hosted
parallelism automatically. A new organisation needs either a grant request or
an Azure subscription linked with billing configured, after which the free
grant applies.

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
| FastAPI edge | the desktop | starts runs, reads and writes their files |
| audio pipeline | the desktop | needs the GPU |
| job history | SQLite on the desktop | must match the processes it describes |
| rendered songs | the desktop | 14 files a song; a single mp3 is 69 times a page load |

That last row is also why serving audio from Azure would be a mistake even
though it is the obvious place to put files. One song's renders are around
100 MB. The quota that comfortably carries a million page views carries a
thousand songs, and the files are already sitting on the machine that made
them.
