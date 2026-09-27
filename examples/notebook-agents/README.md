# Scarlet Composer Studio — LLM Agent Fleet Tutorial

A self-contained stack for one notebook: `06_llm_agent_variance.ipynb`,
which launches a **real** `scarlet-agents` fleet (one head, two workers) and
asks it a question in plain English. Unlike `examples/notebooks` (five
tutorials that simulate everything inside one kernel process), this
notebook controls real, separate containers via the Docker SDK - the head
runs an actual LLM tool-calling loop and dispatches to the two workers over
Redis, exactly as a real deployment would.

Each worker's private data comes from its own CSV file (`data/worker1.csv`,
`data/worker2.csv`) via `data_connectors.CsvConnector` - real separate
containers, so each just gets pointed at its own file with `CSV_PATH`.

---

## What this brings up

| Service | Role |
|---|---|
| `redis` | Self-hosted, host port `6380` (offset from the default to avoid clashing with a real Redis already running locally) |
| `scarlet-composer` | Composer UI, `AUTH_ENABLED=false` - watch the Agents tab while the notebook brings its fleet up |
| `jupyter` | The tutorial notebook - **not** the same image as `examples/notebooks`, see below |

The agent fleet itself (head + 2 workers) is **not** started by this
compose file - notebook 06 launches it itself, from inside a cell, once
you provide LLM credentials there. That's the point of this example: to
show the agent lifecycle happening, not just its result.

---

## Why `jupyter` needs the Docker socket

`docker/jupyter-agents/Dockerfile` extends `scarlet-agents` (not
`scarlet-agent-base`) and adds the `docker` Python package on top of
`jupyterlab`/`pandas`/`matplotlib` - the one new dependency this notebook
needs. At runtime, the `jupyter` service here mounts
`/var/run/docker.sock` in, so the notebook can create and tear down
sibling containers directly. That's a real, meaningful step up in what
this container can do compared to every other notebook in this repo -
deliberately kept in its own image and its own example, so the plain SDK
tutorials never need this capability.

---

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- An LLM endpoint + API key (OpenAI-compatible - Anthropic's compatibility
  layer works) - not needed until you actually run notebook 06's
  credentials cell

---

## 1. Configure environment

```bash
cp .env.example .env
```

Only `REDIS_AUTH_TOKEN` is required - pick any password, Redis is
self-hosted by this compose file, nothing external to point at.

---

## 2. Start the stack

```bash
docker compose up --build -d
```

---

## 3. Open JupyterLab and run the notebook

Visit [http://localhost:8888](http://localhost:8888), open
`06_llm_agent_variance.ipynb`, and run it cell by cell. You'll be prompted
for your LLM base URL, API key, and model name partway through - those
values only ever reach the head container's environment.

Optionally, open [http://localhost:8501](http://localhost:8501) (the
Composer UI) in a second tab first, and watch its Agents page as the
notebook brings the fleet online.

---

## 4. Tear down

```bash
docker compose down
```

The notebook's own cleanup cells stop and remove the agent containers it
launched; this tears down `redis`/`scarlet-composer`/`jupyter` themselves.
