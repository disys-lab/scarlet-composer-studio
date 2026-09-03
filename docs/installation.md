# Installation

---

## Requirements

- Python 3.9+
- Redis 6+ with AUTH enabled
- Docker Engine 24+ (for containerised deployments)

---

## Option A — pip (agents only)

For worker and head agent code — everything needed to use `Mapper`, `Federator`, and `Messenger`:

```bash
pip install scarlets
```

---

## Option B — pip (full stack)

For the operator dashboard and CLI as well:

```bash
pip install scarlets scarletcomposer
```

---

## Option C — from source (development)

```bash
git clone https://github.com/disys-lab/scarlet-composer-studio
cd scarlet-composer-studio

# Install both packages in editable mode
pip install -e .

# Verify
scarlet-composer --version
```

---

## Option D — Docker images

Pre-built images are published to `ghcr.io/disys-lab/`:

| Image | Contents |
|---|---|
| `ghcr.io/disys-lab/scarlet-agent-base` | `scarlets` + supervisor — the base every agent container extends |
| `ghcr.io/disys-lab/scarlet-composer` | `composer-api` (FastAPI) + `composer-ui` (Next.js) operator dashboard |
| `ghcr.io/disys-lab/scarlet-agents` | The [harness](harness/index.md) — decentralized agentic `Skill` runtime |

```bash
# Run the Composer UI
docker run -d \
  -p 8501:3000 \
  -e REDIS_HOST=your-redis-host \
  -e REDIS_AUTH_TOKEN=your-redis-password \
  ghcr.io/disys-lab/scarlet-composer:latest
```

See [Docker Images](deployment/docker.md) for build instructions and how to extend the agent base.

---

## Verify installation

Set the minimum required environment variables and run a quick smoke test:

```bash
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_AUTH_TOKEN=your-password
export APP_ID=test
export NODE_ADDRESS=local
```

```python
from scarlets.core.Mapper import Mapper
import numpy as np

m = Mapper("smoke_test")
m.Map(np.array([1.0, 2.0, 3.0]), key="local")
values, ok, _ = m.AllGather()
print(ok, values)   # True  {"local": array([1., 2., 3.])}
m.clearAll()
```

If you see `True` and the array, everything is wired up correctly.

---

## Launch the Composer UI

The operator dashboard (`composer-api` + `composer-ui`) is a Docker image, not
a pip-installed CLI command — see [Option D](#option-d-docker-images) above,
or [Docker Images](deployment/docker.md) for building it locally. The
`scarlet-composer` CLI installed by `pip install scarletcomposer` covers a
different job: parsing `#scarlet` declarations from source files
(`scarlet-composer composer compose <dir>`) — see [CLI Reference](reference/cli.md).
