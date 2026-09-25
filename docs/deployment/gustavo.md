# Gustavo Integration

[Gustavo](https://github.com/disys-lab/gustavo) is the Nebula-based edge orchestrator used to deploy and manage Scarlet agents on distributed nodes. It's a web platform (Next.js UI + FastAPI backend) with a companion CLI for the same operations - node enrollment, Docker image distribution, device group management, and the Nebula overlay network all go through one of these two surfaces.

---

## Concepts

| Gustavo concept | Scarlet equivalent |
|---|---|
| **App** | A named Docker image + environment configuration |
| **Device group** | A Messenger bus namespace — all nodes in a group run the same set of apps |
| **Worker** | The `gustavo worker` process running on a physical edge node - self-registers with the manager, then pulls whatever apps its device group assigns it |
| **Manager** | The Nebula certificate authority + Gustavo API server |

Enrollment is **pull-based**, not push-based: an admin never tells the manager "add node X to group Y." A node joins a group by running the worker *on that node itself*, configured with `DEVICE_GROUP=<name>`.

---

## Installing the Gustavo CLI

Optional - only needed if you want to drive Gustavo from a terminal instead of the web UI. It's published on a private Gemfury feed, not public PyPI:

```bash
pip3 install --no-cache-dir --extra-index-url https://pypi.fury.io/osu-home-stri/ gustavo
```

Verify:
```bash
gustavo --version
gustavo --help
```

It reads all configuration from one `KEY=VALUE` env file, pointed to by `GUSTAVO_CONFIG_FILE`:
```bash
export GUSTAVO_CONFIG_FILE=/path/to/your.env
```

---

## Starting the Manager

The manager runs five services: Registry, Redis, MongoDB, the Nebula Manager, and Syncer.

```bash
gustavo manager up mongo      # SERVICE is a positional argument, not a flag
gustavo manager up manager
# or bring up everything at once:
gustavo manager up all
```

**Health check:**
```bash
gustavo manager check   # pings http://{MANAGER_HOST}:{MANAGER_PORT}/api/v2/status
gustavo ping             # same idea, platform-wide
```

---

## App Configuration YAML

Register an app by providing a YAML config that describes the Docker image and its environment:

```yaml
# hello_agent_config.yaml
hello-agent:
    docker_image: your-registry.io/hello-agent:latest
    env_vars:
        APP_ID: hello-agent
        REDIS_HOST: <your-redis-host>
        REDIS_PORT: "6379"
        REDIS_AUTH_TOKEN: <your-password>
        NODE_ADDRESS: ""          # leave empty — Nebula alias resolution fills this in
        DEVICE_GROUP: quickstart_subagent
        MANAGER_HOST: <manager-ip>
        MANAGER_PORT: "8080"
    networks:
        - host
    volumes:
        - /tmp/:/tmp/
    running: True
    rolling_restart: True
    containers_per:
        server: 1               # 1 container per enrolled node
    privileged: False
    devices: []
```

Register it:
```bash
gustavo apps create -n hello-agent -f hello_agent_config.yaml
```

`-n`/`-f` are the only options `apps create` takes - there's no flag to set a default device group on the app itself. Group membership is set on the *device group*, not the app (see below).

---

## Device Groups

Device groups map to Messenger bus namespaces, and are what actually associates an app with the nodes that should run it:

```bash
# Global coordination bus (Pattern A head)
gustavo device-group create -n quickstart_headagent -a hello-agent

# Local worker bus
gustavo device-group create -n quickstart_subagent -a hello-agent
```

`-a` (repeatable) is what assigns apps to the group - nodes that self-enroll into it receive every app listed here.

---

## Node Enrollment

Enrollment happens **on the node itself** - nothing runs `add-node` from the manager side; that command doesn't exist. Three ways to get a worker running, in order of how much you need installed on the node:

**1. `gustavo worker up` (CLI installed on the node)**

```bash
gustavo worker up
# or, on hardware with an actual GPU nvidia-container-toolkit can expose:
gustavo worker up --gpu
```

Reads `GUSTAVO_CONFIG_FILE` (`MANAGER_HOST`, `REDIS_HOST`, `REGISTRY_HOST`, `DEVICE_GROUP`, Nebula credentials, ...) and registers this node with the manager. Rather than hand-writing that file, download one scoped to your own identity and the target group directly from a running Gustavo instance:
```bash
curl -u <username>:<secret> http://<gustavo-host>:<port>/api/device-groups/<group-name>/worker-env -o worker.env
```

**2. `docker-compose.yml` (no CLI needed)**
```bash
curl -u <username>:<secret> http://<gustavo-host>:<port>/api/device-groups/<group-name>/worker-compose -o docker-compose.yml
docker compose up -d
```

**3. A self-contained launcher script (no CLI, no companion file)**
```bash
curl -u <username>:<secret> http://<gustavo-host>:<port>/api/device-groups/<group-name>/worker-script -o worker.sh
bash worker.sh
```
(`worker-script-windows` for a `.bat` equivalent on Windows nodes.)

All three are also available as download buttons on that device group's page in the web UI - the API routes above are what those buttons call.

After the worker starts, the node:
1. Registers with the Nebula Manager and receives an overlay IP
2. Writes its overlay IP to the `node-aliases` Redis key
3. Pulls every app assigned to `DEVICE_GROUP` and starts the containers

---

## gustavo_init.sh (quickstart)

The file at `examples/quickstart/gustavo_init.sh` automates the full bootstrap for a single-machine deployment:

```sh
#!/bin/sh
# Full bootstrap: MongoDB → manager → hello-agent app → two device groups
set -e

gustavo manager up mongo
sleep 15
gustavo manager up manager

until gustavo manager check 2>&1 | grep -q "Manager Up"; do
    echo "[quickstart] Manager not ready, retrying in 5 s..."
    sleep 5
done

# Register hello-agent app (reads REDIS_HOST etc from env)
gustavo apps create -n hello-agent -f /tmp/hello_agent_config.yaml

# Two device groups — one per Messenger bus, each granted the app
gustavo device-group create -n quickstart_headagent -a hello-agent
gustavo device-group create -n quickstart_subagent  -a hello-agent

tail -f /dev/null   # keep container alive for CLI access
```

---

## Common CLI Commands

```bash
# App management
gustavo apps list
gustavo apps create -n <name> -f <yaml>
gustavo apps delete -n <name>

# Device groups
gustavo device-group list
gustavo device-group create -n <group> [-a <app>]...
gustavo device-group update -n <group> -a <app>
gustavo device-group delete -n <group>

# Worker (run on the edge node itself)
gustavo worker up [--gpu]
gustavo worker remove
gustavo worker recreate

# Manager
gustavo manager up <registry|redis|mongo|manager|syncer|all>
gustavo manager stop <service>
gustavo manager check
gustavo ping

# Live metrics from enrolled workers
gustavo cache vitals
```

There is no `gustavo node` command group - node-level operations happen by running `gustavo worker` commands *on that node*, not by an admin targeting a node's IP from elsewhere.

---

## Node Identity and Alias Resolution

When `NODE_ADDRESS` is not set (and `MANAGER_HOST`/`MANAGER_PORT` point at
this deployment's BackgroundServer), Scarlet agents query it, which
resolves the *caller's own IP* against the `node-aliases` Redis key - a
single JSON-encoded string, not a Hash (`json.loads(r.get("node-aliases"))`,
matched by scanning for the entry whose `hostname` equals the caller's IP -
not a direct `HGET` by hostname).

Gustavo populates this during worker enrollment. As long as `MANAGER_HOST`/
`MANAGER_PORT` correctly point at the BackgroundServer, agents get the
correct Nebula IP without any static configuration.

See [Node Identity](../concepts/identity.md) for the full resolution chain.
