# Scarlet Composer Studio — SDK Tutorials

A JupyterLab environment preloaded with five runnable tutorials for the
`scarlets` SDK - not a deployable agent, an exploration/teaching environment
for learning `Messenger`, `Mapper`, and `Federator` interactively.

| Notebook | Covers |
|---|---|
| `01_messenger_basics.ipynb` | Agent-to-agent messaging: `Send`/`Receive`/`Broadcast`/`GatherStatus` |
| `02_mapper_basics.ipynb` | Distributed key-value store: `Map`/`AllGather`/`Reduce`/`resetAll`/`clearAll` |
| `03_federator_aggregation.ipynb` | Federated aggregation across simulated workers |
| `04_timeseries_with_mapper.ipynb` | `Map(..., timeseries=True)` - accumulating a time series under one key |
| `05_federated_linear_regression.ipynb` | A toy FedAvg-style gradient descent, end to end |

Every notebook uses fixed scarlet/agent names and starts with a cleanup
cell, so re-running one from the top is always safe - no leftover state
from a previous run.

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- A Redis 6+ instance with AUTH enabled
- Pull access to `ghcr.io/disys-lab/`

---

## 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — the only required fields:

| Variable | What to set |
|---|---|
| `REDIS_HOST` | Hostname or IP of your Redis instance |
| `REDIS_AUTH_TOKEN` | Redis password |

**Running Redis locally:**
```bash
docker run -d -p 6379:6379 redis/redis-stack:7.4.0-v1 redis-server --requirepass your-password
```
Then set `REDIS_HOST=host.docker.internal` in `.env`.

---

## 2. Start the stack

```bash
docker compose up --build -d
```

Check progress:
```bash
docker compose logs -f scarlet-notebooks
```

---

## 3. Open JupyterLab

Visit [http://localhost:8888](http://localhost:8888) and open any of the six
notebooks in the file browser. No token/login is required - see
`docker/jupyter/Dockerfile` if you need to run this somewhere less
trusted than a private network.

---

## 4. Tear down

```bash
docker compose down
```

---

## Going further

Once you're comfortable with the primitives here, see
[docs/quickstart.md](../../docs/quickstart.md) for a real multi-container
agent deployment, or [docs/guides/federation.md](../../docs/guides/federation.md)
for the full `Federator` reference these tutorials only introduce.
