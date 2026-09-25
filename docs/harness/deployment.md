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
`data-connectors` wheel — `scarlets` comes from the `scarlet-agent-base`
image itself, not from `dist/`):

```bash
python3 setup_connectors.py bdist_wheel

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

## Local data sources (`~/.scarlet/config.yaml`)

[Local-First Data Access](concepts.md#local-first-data-access) reads this
file from `Path.home() / ".scarlet" / "config.yaml"` at runtime — inside a
container that means the **container's** home directory, not the host's.
Neither Dockerfile in this repo sets a `USER`, so `scarlet-agents` runs as
root and `Path.home()` resolves to `/root`. The file has to actually be
present at that path *inside the running container* — Gustavo/Docker won't
put it there for you, and there's no push path from the Composer UI into
this file by design (see `local_config.py`'s own docstring).

Two ways to get it there, `docker run`:

```bash
# Option 1 — bind-mount to match the container's actual home (/root, since
# neither Dockerfile sets USER). Breaks silently if a future USER directive
# changes that.
docker run --rm \
  -v ~/.scarlet:/root/.scarlet:ro \
  -e REDIS_HOST=... -e REDIS_AUTH_TOKEN=... \
  scarlet-agents:latest

# Option 2 (recommended) — mount anywhere, point SCARLET_LOCAL_CONFIG at
# it explicitly. local_config.py checks this env var before falling back
# to Path.home(), so this doesn't depend on the container's home dir at all.
docker run --rm \
  -v ~/.scarlet/config.yaml:/etc/scarlet/config.yaml:ro \
  -e SCARLET_LOCAL_CONFIG=/etc/scarlet/config.yaml \
  -e REDIS_HOST=... -e REDIS_AUTH_TOKEN=... \
  scarlet-agents:latest
```

Same idea in compose (add to `scarlet-agents`'s service definition in
`harness/docker-compose.yml`):

```yaml
    volumes:
      - ~/.scarlet/config.yaml:/etc/scarlet/config.yaml:ro
    environment:
      - SCARLET_LOCAL_CONFIG=/etc/scarlet/config.yaml
```

This only works if the file already exists at that path on **whichever
host the container actually runs on**. For a Gustavo-managed remote worker
node, that means it must already be on that node's disk before Gustavo
starts the container — Gustavo's own app volume-mount field (host path →
container path) assumes the host path exists, it doesn't create it.
Getting the file onto a specific remote node in the first place is a
separate, out-of-band step (e.g. `scp` at node enrollment) — deliberately
not something either Gustavo or the Composer UI automates, consistent with
`local_config.py`'s "no push path, ever" design.

---

See [Getting Started](getting-started.md) for running the harness (and its
tests) outside Docker.
