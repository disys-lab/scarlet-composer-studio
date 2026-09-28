# Scarlet Composer Studio — SDK Tutorials

A JupyterLab environment preloaded with six runnable tutorials for the
`scarlets` SDK - not a deployable agent, an exploration/teaching environment
for learning `Messenger`, `Mapper`, and `Federator` interactively, then
putting them to work behind a real LLM-driven agent fleet.

| Notebook | Covers |
|---|---|
| `01_messenger_basics.ipynb` | Agent-to-agent messaging: `Send`/`Receive`/`Broadcast`/`GatherStatus` |
| `02_mapper_basics.ipynb` | Distributed key-value store: `Map`/`AllGather`/`Reduce`/`resetAll`/`clearAll` |
| `03_federator_aggregation.ipynb` | Federated aggregation across simulated workers |
| `04_timeseries_with_mapper.ipynb` | `Map(..., timeseries=True)` - accumulating a time series under one key |
| `05_federated_linear_regression.ipynb` | A toy FedAvg-style gradient descent, end to end |
| `06_llm_agent_variance.ipynb` | A real 3-container agent fleet, asked a question in plain English |

Notebooks 01-05 run entirely inside the JupyterLab kernel. **Notebook 06 is
different** - it works against real, separate `scarlet-agents` containers.
See [Notebook 06](#notebook-06--the-agent-fleet) below.

Every notebook uses fixed scarlet/agent names and starts with a cleanup or
parameter cell, so re-running one from the top is always safe.

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Pull access to `ghcr.io/disys-lab/`
- For notebook 06 only: an OpenAI-compatible LLM endpoint and key

Redis is started by this compose file - you don't need your own.

---

## 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env`. The only always-required field:

| Variable | What to set |
|---|---|
| `REDIS_AUTH_TOKEN` | Any non-empty password; Redis is started with it |

For notebook 06, also fill in `LLM_BASE_URL`, `LLM_API_KEY`, and
`LLM_MODEL`. Leave them blank if you're only running 01-05.

---

## 2. Start the stack

```bash
docker compose up -d
```

Three services come up: Redis, the Composer UI, and JupyterLab. Every one
runs a published image - nothing is built locally.

```bash
docker compose logs -f jupyter
```

---

## 3. Open JupyterLab

[http://localhost:8888](http://localhost:8888) - all six notebooks are in
the file browser. No token/login is required; see
`docker/jupyter/Dockerfile` if you need to run this somewhere less trusted
than a private network.

The Composer UI is at [http://localhost:8501](http://localhost:8501), where
you can watch agents register in real time while notebook 06 runs.

---

## 4. Tear down

```bash
docker compose down            # add -v to drop the generated CSV volume too
```

---

## Notebook 06 — the agent fleet

Notebook 06 needs three more containers: one agent head and two workers.
They are declared in the **same** `docker-compose.yml` under a `agents`
profile, which means `docker compose up` above deliberately skips them.

You do not start them by hand. The notebook brings them up itself, by
running `docker compose --profile agents up -d` against that same file -
which it can see because the compose file bind-mounts itself, and the
Docker socket, into the jupyter container.

The notebook then generates each worker's private CSV into a shared volume,
waits for all three agents to register on the Redis bus, and asks the head
a plain-English question. The head's LLM decides which skills to call and
dispatches to the workers over Redis.

Its teardown cell removes the three agent containers and leaves the rest of
the stack running, so you can re-run from the top without restarting
everything.

### Running it through Gustavo instead

`gustavo-app.yaml`, next to this README, declares the same topology as a
Gustavo app config - for running the tutorial across real edge nodes rather
than one host's Docker daemon:

```bash
gustavo apps create -f gustavo-app.yaml -n scarlet-tutorial -d <device-group>
```

The one thing that matters to the notebook is `GUSTAVO_MANAGED_AGENTS=true`,
set on the jupyter app there. Notebook 06 reads it and skips both its launch
and its teardown steps - waiting for the agents on the bus instead of
starting them, and leaving them alone at the end. Nothing else in the
notebook changes, because the agent identity variables
(`APP_ID`, `HEAD_NODE_ADDRESS`, `WORKER_NODE_ADDRESSES`) are the same ones
the compose file interpolates.

This is also the more honest version of the tutorial: under Gustavo each
worker reads data that already lives on its own node, rather than CSVs the
notebook generated - the agent goes to the data instead of the reverse.

---

## Going further

Once you're comfortable with the primitives here, see
[docs/quickstart.md](../../docs/quickstart.md) for a real multi-container
agent deployment, or [docs/guides/federation.md](../../docs/guides/federation.md)
for the full `Federator` reference these tutorials only introduce.
