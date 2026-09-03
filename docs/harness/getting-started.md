# Getting Started

## Install

From this monorepo's root, the harness depends on two sibling packages
built from the same checkout — `scarlets` and `data-connectors`:

```bash
cd harness/
python3 -m venv .venv && source .venv/bin/activate
pip install -e . -r requirements.txt
```

## Run the tests

```bash
python3 -m pytest tests/ -v
```

`tests/test_median_skill.py` spins up a disposable local Redis via `docker
run` and drives a full distributed median computation through 3 real
worker subprocesses and the actual dispatch code — no mocks on the
`scarlets` side. Six tests that exercise a real LLM backend are opt-in
(skipped unless `LLM_BASE_URL` is set), so the default run stays fast and
credential-free.

## Run it locally

Minimum environment for a worker:

```bash
export REDIS_HOST=localhost
export REDIS_AUTH_TOKEN=...
export ROLE=worker
export APP_ID=my-app
export NODE_ADDRESS=local
```

```bash
python3 -m scarlet_agentic_harness
```

A worker reports itself online with its discovered skills
(`worker online, skills=['combine', 'median', 'sum'], ...`). Point a head
at the same `APP_ID`/Redis (`ROLE=head`) and it can dispatch to that worker
immediately — no registration step beyond both processes sharing the same
bus.

To talk to it in natural language instead of calling a skill directly, set
`LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` on the head — any
OpenAI-SDK-compatible endpoint works, including Anthropic's
compatibility layer.

## Add a new skill

A skill is one new module under `scarlet_agentic_harness/skills/`
implementing `contribute()`/`coordinate()` — see [Core Concepts](concepts.md#the-skill-interface)
for the interface, and `skills/median.py` for the smallest complete
reference implementation. Nothing in `head.py`/`worker.py` needs to
change — `skills/registry.py` discovers it automatically.

## Give a worker local data sources

Create `~/.scarlet/config.yaml` on the node (see
[Local-First Data Access](concepts.md#local-first-data-access) for the file
shape) — no restart-free hot reload is required to try it, since a worker
rebuilds its tag cache from this file periodically as well as at startup.

## Next steps

[Deployment](deployment.md) covers the Docker image and running alongside
Gustavo/composer.
