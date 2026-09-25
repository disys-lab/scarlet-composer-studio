# Interactive Notebooks

A JupyterLab environment preloaded with five runnable tutorials for the
`scarlets` SDK — the fastest way to get a feel for `Messenger`, `Mapper`,
and `Federator` without writing a full agent first.

| Notebook | Covers |
|---|---|
| `01_messenger_basics.ipynb` | Agent-to-agent messaging: `Send`/`Receive`/`Broadcast`/`GatherStatus` |
| `02_mapper_basics.ipynb` | Distributed key-value store: `Map`/`AllGather`/`Reduce`/`resetAll`/`clearAll` |
| `03_federator_aggregation.ipynb` | Federated aggregation across simulated workers |
| `04_timeseries_with_mapper.ipynb` | `Map(..., timeseries=True)` — accumulating a time series under one key |
| `05_federated_linear_regression.ipynb` | A toy FedAvg-style gradient descent, end to end |

Every notebook uses fixed scarlet/agent names and starts with a cleanup
cell, so re-running one from the top is always safe.

---

## Running it

```bash
cd examples/notebooks
cp .env.example .env    # fill in REDIS_HOST, REDIS_AUTH_TOKEN
docker compose up --build -d
```

Then open [http://localhost:8888](http://localhost:8888) — no token/login
required by default. See [examples/notebooks/README.md](https://github.com/disys-lab/scarlet-composer-studio/blob/main/examples/notebooks/README.md)
for the full walkthrough.

---

## The image

`docker/jupyter/Dockerfile` extends `scarlet-agent-base` directly — the
`scarlets` SDK is already baked in; the only additions are `jupyterlab`,
`pandas`, and `matplotlib`, installed from PyPI. Unlike `scarlet-composer`
or the [harness](../harness/index.md), it doesn't need a locally-built
wheel — pull access to `ghcr.io/disys-lab/scarlet-agent-base` is enough:

```bash
docker build --build-arg BASE_VERSION=0.5.0 \
  -f docker/jupyter/Dockerfile -t scarlet-notebooks:dev .
```

Published as `ghcr.io/disys-lab/scarlet-notebooks` by the same CI pipeline
as the other three images (see [Docker Images](../deployment/docker.md)) —
gated on the `#notebooks-dockerbuild` commit-message catchphrase.

---

## Going further

Each notebook only introduces its primitive — for the full reference, see
[Scarlet Primitives](../concepts/scarlets.md) and
[Federated Aggregation](federation.md). For a real multi-container agent
deployment (not just a notebook kernel talking to Redis), see
[Quickstart](../quickstart.md).
