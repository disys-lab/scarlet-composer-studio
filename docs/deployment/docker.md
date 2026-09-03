# Docker Images

Three images are built from this repository and published to `ghcr.io/disys-lab/`:

| Image | Base | Contents |
|---|---|---|
| `scarlet-agent-base` | `python:3.11-slim` | `scarlets` package, `supervisor` — the base every agent container extends |
| `scarlet-composer` | `ubuntu:24.04` | `composer-api` (FastAPI) + `composer-ui` (Next.js) operator dashboard, combined in one container |
| `scarlet-agents` | `scarlet-agent-base` | The [harness](../harness/index.md) — decentralized agentic `Skill` runtime |

All three share one build pipeline (`.github/workflows/multi-build.yml`): `scarlets`, `scarletcomposer`, and `data-connectors` wheels are built exactly once per CI run from that run's own commit and consumed by every image that needs them — no image re-derives its own copy.

---

## Extending the Agent Base Image

`scarlet-agent-base` is the recommended starting point for any agent container.

```dockerfile
FROM ghcr.io/disys-lab/scarlet-agent-base:0.5.0

# Install your agent's dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy your agent code
COPY hello_agent.py /app/hello_agent.py

# Supervisor will restart the agent on crash
COPY supervisord.conf /etc/supervisor/conf.d/agent.conf

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/agent.conf"]
```

See `examples/quickstart/hello_agent/` for a complete, working example of this pattern.

### supervisord.conf template

```ini
[supervisord]
nodaemon=true
logfile=/var/log/supervisor/supervisord.log

[program:agent]
command=python /app/hello_agent.py
directory=/app
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/agent.err.log
stdout_logfile=/var/log/supervisor/agent.out.log
environment=APP_ID="%(ENV_APP_ID)s",NODE_ADDRESS="%(ENV_NODE_ADDRESS)s"
```

---

## Building Locally

All three Dockerfiles use the same build context: **the repository root**, not the directory the Dockerfile lives in — `composer-app` and the harness both need sibling access to `dist/` for pre-built wheels.

Build the wheels once, then build any (or all) of the images:

```bash
# From the repo root
python3 setup.py bdist_wheel
python3 setup_composer.py bdist_wheel
python3 setup_connectors.py bdist_wheel   # only needed for scarlet-agents

# scarlet-agent-base — LOCAL=true consumes the wheel just built above
docker build --build-arg VERSION=<version-from-dist-filename> --build-arg LOCAL=true \
  -f docker/agent-base/Dockerfile -t scarlet-agent-base:dev .

# scarlet-composer
docker build -f docker/composer-app/Dockerfile -t scarlet-composer:dev .

# scarlet-agents — extends the agent-base image just built above
docker build --build-arg BASE_VERSION=dev \
  -f harness/Dockerfile -t scarlet-agents:dev .
```

`<version-from-dist-filename>` is the version string in the wheel setuptools-scm actually produced (`ls dist/scarlets-*.whl`) — it won't always match a plain `git describe`, see the comments in `multi-build.yml`'s `agent-dockerbuild` job if you're scripting this.

---

## Composer UI Container

The composer container exposes one port:

| Port | Service |
|---|---|
| `3000` | Next.js UI (public) |

FastAPI (`composer-api`, port 8000) binds to `127.0.0.1` only inside the container — not reachable from outside it.

```bash
docker run -d \
  --name scarlet-composer \
  -p 8501:3000 \
  -e REDIS_HOST=your-redis-host \
  -e REDIS_PORT=6379 \
  -e REDIS_AUTH_TOKEN=your-password \
  -e AUTH_ENABLED=false \
  ghcr.io/disys-lab/scarlet-composer:latest
```

### Node identity resolution (`background-server`)

A real multi-node deployment also runs `background_server.py` (same image,
different `command`) as its own service, `network_mode: host`, so it resolves
each caller's real IP correctly:

```yaml
background-server:
  image: ghcr.io/disys-lab/scarlet-composer:latest
  network_mode: host
  command: ["python", "/app/docker/composer-app/background_server.py"]
  environment:
    - BACKGROUND_SERVER_PORT=9098
```

Not needed for local development where `NODE_ADDRESS` is set explicitly — see the quickstart's own compose file.

---

## Minimal Docker Compose

For quick local testing without Gustavo:

```yaml
# docker-compose.minimal.yml
services:
  redis:
    image: redis/redis-stack:7.4.0-v1
    ports: ["6379:6379"]
    command: redis-server --requirepass mypassword

  composer:
    build:
      context: .
      dockerfile: docker/composer-app/Dockerfile
    ports:
      - "8501:3000"
    environment:
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_AUTH_TOKEN: mypassword
      AUTH_ENABLED: "false"
    depends_on: [redis]

  hello-agent:
    image: ghcr.io/disys-lab/scarlet-agent-base:0.5.0
    environment:
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_AUTH_TOKEN: mypassword
      APP_ID: quickstart
      NODE_ADDRESS: local
      DEVICE_GROUP: quickstart_subagent
    volumes:
      - ./examples/quickstart/hello_agent/hello_agent.py:/app/hello_agent.py
    command: python /app/hello_agent.py
    depends_on: [redis]
```

```bash
python3 setup.py bdist_wheel && python3 setup_composer.py bdist_wheel   # composer's Dockerfile needs these in dist/
docker compose -f docker-compose.minimal.yml up --build
```

---

## Environment Variables in Containers

All environment variables are read at runtime — no build-time baking (with one exception: `NEXT_PUBLIC_AUTH_ENABLED`, a Next.js build-arg on `composer-app` — see [Environment Variables](env-vars.md)).

The minimum set for an agent container:

```bash
REDIS_HOST=...
REDIS_AUTH_TOKEN=...
APP_ID=...
NODE_ADDRESS=...     # or leave unset for Gustavo alias resolution
DEVICE_GROUP=...
```

---

## Publishing to a Private Registry

```bash
# Tag and push to your own registry
docker tag ghcr.io/disys-lab/scarlet-agent-base:0.5.0 \
    your-registry.io/scarlet-agent-base:0.5.0

docker push your-registry.io/scarlet-agent-base:0.5.0
```

If you use Gemfury for private distribution:

```bash
export GEMFURY_TOKEN=...
docker login docker.fury.io -u $GEMFURY_TOKEN -p $GEMFURY_TOKEN
docker tag ghcr.io/disys-lab/scarlet-agent-base:0.5.0 \
    docker.fury.io/disyslab/scarlet-agent-base:0.5.0
docker push docker.fury.io/disyslab/scarlet-agent-base:0.5.0
```
