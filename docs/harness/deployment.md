# Deployment

## Docker image

`harness/Dockerfile` extends `ghcr.io/disys-lab/scarlet-agent-base`, matching
scarlet-composer-studio's own `hello_agent` quickstart convention: extend
the base image, copy the agent in, run it under `supervisord` for
autorestart. Built and published as `ghcr.io/disys-lab/scarlet-agents` by
this repo's CI (`.github/workflows/multi-build.yml`'s `harness-dockerbuild`
job, triggered by the `#harness-dockerbuild` commit-message catchphrase) —
built from a shared wheel artifact (`scarlets`, `scarletcomposer`,
`data-connectors`) produced once per run and reused across every image, and
from the exact `scarlet-agent-base` image the same run just pushed.

Build locally (context must be the monorepo root, not `harness/` itself —
this Dockerfile needs sibling access to `dist/` for the pre-built
`data-connectors` wheel):

```bash
docker build \
  --build-arg BASE_VERSION=0.5.0 \
  -f harness/Dockerfile \
  -t scarlet-agents:latest .
```

Run standalone (for local testing without compose):

```bash
docker run --rm \
  -e REDIS_HOST=... -e REDIS_AUTH_TOKEN=... \
  -e ROLE=worker -e APP_ID=scarlet-agents -e NODE_ADDRESS=local \
  -e LLM_BASE_URL=... -e LLM_API_KEY=... -e LLM_MODEL=... \
  scarlet-agents:latest
```

Or via `harness/docker-compose.yml`, which runs it alongside a
`scarlet-composer` sibling container for local dev.

`ROLE` picks head vs. worker inside `__main__.py` — same image either way.
Defaults to `worker`: `__main__.py`'s `ROLE=head` branch is currently an
interactive REPL (reads `sys.stdin` line by line), not a headless daemon.
Under `supervisord` in a detached container, `stdin` is closed, so
`ROLE=head` would hit EOF immediately and crash-loop under autorestart. Use
`docker run -it ... -e ROLE=head ...` (bypassing supervisord, or with
stdin properly attached) for head/manual-dispatch use until `__main__.py`'s
head branch becomes a real daemon. `mcp_server.py`
(`python -m scarlet_agentic_harness.mcp_server`, `MCP_TRANSPORT=
streamable-http`) is a genuine headless alternative for a head role — it
needs no stdin at all — but isn't wired as this image's default `CMD`; run
it as a separate `docker run`/supervisord program if you need an
MCP-reachable head.

## Running the tests

```bash
cd harness/
python3 -m venv .venv && source .venv/bin/activate
pip install -e . -r requirements.txt
python3 -m pytest tests/ -v
```

`tests/test_median_skill.py` spins up a disposable local Redis via `docker
run` (removed at the end of the session, never a real deployment target),
spawns 3 real worker subprocesses, and drives a full median computation
through the actual dispatch code — no mocks on the scarlets side. Six
real-LLM tests are opt-in (skipped unless `LLM_BASE_URL` is set), so the
regular suite stays fast and credential-free.
