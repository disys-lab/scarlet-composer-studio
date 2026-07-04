# Docker Images

Two pre-built images are published to `ghcr.io/disys-lab/`:

| Image | Tag | Base | Contents |
|---|---|---|---|
| `ghcr.io/disys-lab/scarlet-agent-base` | `0.5.0` | `python:3.11-slim` | `scarlets` package, `supervisor` |
| `ghcr.io/disys-lab/scarlet-composer` | `0.5.0` | `scarlet-agent-base` | `scarletcomposer`, Streamlit, Tornado |

---

## Extending the Agent Base Image

The `scarlet-agent-base` image is the recommended starting point for any agent container.

```dockerfile
FROM ghcr.io/disys-lab/scarlet-agent-base:0.5.0

# Install your agent's dependencies
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy your agent code
COPY hello_agent.py /app/hello_agent.py

# Supervisor will restart the agent on crash
COPY supervisord.conf /etc/supervisor/conf.d/agent.conf

CMD ["supervisord", "-c", "/etc/supervisor/supervisord.conf"]
```

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

```bash
# Build the agent base
docker build -t scarlet-agent-base:dev -f Dockerfile.agent .

# Build the Composer UI
docker build -t scarlet-composer:dev -f Dockerfile.composer .
```

---

## Composer UI Container

The Composer container exposes two ports:

| Port | Service |
|---|---|
| `8501` | Streamlit UI |
| `9099` | Tornado identity server |

```bash
docker run -d \
  --name scarlet-composer \
  -p 8501:8501 \
  -p 9099:9099 \
  -e REDIS_HOST=your-redis-host \
  -e REDIS_PORT=6379 \
  -e REDIS_AUTH_TOKEN=your-password \
  -e APP_ID=quickstart \
  -e NODE_ADDRESS=local \
  ghcr.io/disys-lab/scarlet-composer:0.5.0
```

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
    image: ghcr.io/disys-lab/scarlet-composer:0.5.0
    ports:
      - "8501:8501"
      - "9099:9099"
    environment:
      REDIS_HOST: redis
      REDIS_PORT: 6379
      REDIS_AUTH_TOKEN: mypassword
      APP_ID: quickstart
      NODE_ADDRESS: local
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
      - ./examples/quickstart/hello_agent.py:/app/hello_agent.py
    command: python /app/hello_agent.py
    depends_on: [redis]
```

```bash
docker compose -f docker-compose.minimal.yml up
```

---

## Environment Variables in Containers

All environment variables are read at runtime — no build-time baking. See [Environment Variables](env-vars.md) for the full reference.

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
