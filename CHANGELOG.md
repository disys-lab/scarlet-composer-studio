# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions are the shared setuptools-scm counter `scarlets`/`scarletcomposer`/
`data-connectors` all derive from this repo's git tags — see
`docs/deployment/docker.md` for how that maps to published image tags.

## Unreleased

### Added
- `harness/` — the agentic `Skill` runtime, folded into this repo (from the
  previously-standalone `scarlet-agentic-harness`) with full commit history
  preserved via `git subtree`. Published as `ghcr.io/disys-lab/scarlet-agents`.
- Local-first data access: a worker can read data sources from its own
  site-owned `~/.scarlet/config.yaml`, discovered by other agents via
  feature-level `AgentDialogue` rather than a central registry lookup.
- Centralized data-source broker registry (`/api/data-sources`) for sources
  that genuinely should be shared — no credential is ever stored in
  composer-api, only authorization policy and where to find the broker.
- Composer UI: a real **Logging** page (`/api/logs`, live tail of
  `RedisLogger`'s stream).
- CI now builds `scarlets`/`scarletcomposer`/`data-connectors` wheels
  exactly once per run and shares that artifact across all three Docker
  images, instead of each image independently re-deriving its own copy.

### Fixed
- `composer-dockerbuild`'s CI job was building the old, dead Streamlit-era
  `docker/composer/Dockerfile` — retargeted to the actually-deployed
  `docker/composer-app/Dockerfile`.
- Broker `/query` handler no longer blocks the event loop on synchronous
  driver calls — bounded thread pool per connector.

### Changed
- Composer UI migrated from Streamlit to a Next.js (`composer-ui`) +
  FastAPI (`composer-api`) stack, combined into one container. Node
  identity resolution (`background-server`) now runs as its own service
  rather than bundled into the UI process.

## [0.5.1] — 2026-08-31

First tagged baseline of `scarlets`/`scarletcomposer`, published as
`ghcr.io/disys-lab/scarlet-agent-base:0.5.0` and
`ghcr.io/disys-lab/scarlet-composer:0.5.0`.
