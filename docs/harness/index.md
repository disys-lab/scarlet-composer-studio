# Introduction

The harness is a decentralized agent runtime built on top of this repo's
`scarlets` primitives (`Mapper`, `Federator`, `Messenger`). It defines what
an agent's *task* looks like and how a head and any number of workers carry
one out together — something `scarlets` itself deliberately doesn't define.
Deployed alongside [Gustavo](https://github.com/disys-lab/gustavo) as
`ghcr.io/disys-lab/scarlet-agents`.

## Why this exists

Most agent frameworks assume a central orchestrator that knows every
capability and every data source in advance. That model fights how
industrial sites actually operate: a plant manager runs their own
historian, is territorial about their own data, and won't hand credentials
to a system they don't control. The harness is built around the opposite
default — capability and data-source knowledge live at the edge, and
agents find each other on demand.

Three principles follow from that:

- **A task is a `Skill`, not a script.** Any well-defined distributed
  computation — sum a value across workers, find a median, mint a new
  agent mid-task — implements one small interface. Adding a capability
  means adding a module, never touching the dispatch logic that routes to
  it.
- **Coordination happens by feature, not by infrastructure.** A worker
  asks "who can supply Roll Speed," not "who has a Postgres connection to
  host X." The requester never needs to know what connector, database, or
  site backs an answer — see [Local-First Data Access](concepts.md#local-first-data-access).
- **Code stays static and auditable.** Skills are bundled into the image
  ahead of time, not generated or fetched at runtime. An agent running
  against a live industrial database has to be something a site engineer
  can trust and reason about — free-form code generation trades that away
  for flexibility the platform doesn't need at that layer.

## Where to go next

- **[Core Concepts](concepts.md)** — the `Skill` interface, head/worker
  roles, dispatch, agent-to-agent dialogue, and local-first data access.
  Read this first.
- **[Getting Started](getting-started.md)** — install, run the tests,
  write and run a minimal skill.
- **[Deployment](deployment.md)** — the Docker image and running it
  alongside Gustavo/composer.
