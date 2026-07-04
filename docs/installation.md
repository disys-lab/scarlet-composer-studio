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

| Image | Tag | Contents |
|---|---|---|
| `ghcr.io/disys-lab/scarlet-agent-base` | `0.5.0` | `scarlets` + supervisor |
| `ghcr.io/disys-lab/scarlet-composer` | `0.5.0` | `scarletcomposer` + Streamlit |

```bash
# Run the Composer UI
docker run -d \
  -p 8501:8501 -p 9099:9099 \
  -e REDIS_HOST=your-redis-host \
  -e REDIS_AUTH_TOKEN=your-redis-password \
  ghcr.io/disys-lab/scarlet-composer:0.5.0
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

```bash
scarlet-composer composer gui
```

Opens Streamlit on **port 8501** and starts the Tornado identity server on **port 9099**.

```bash
scarlet-composer composer gui --port 8502 --lport 9100   # custom ports
```
