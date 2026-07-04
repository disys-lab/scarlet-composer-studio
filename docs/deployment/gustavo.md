# Gustavo Integration

[Gustavo](https://github.com/disys-lab/gustavo) is the Nebula-based edge orchestrator used to deploy and manage Scarlet agents on distributed nodes. It handles node enrollment, Docker image distribution, device group management, and the Nebula overlay network.

---

## Concepts

| Gustavo concept | Scarlet equivalent |
|---|---|
| **App** | A named Docker image + environment configuration |
| **Device group** | A Messenger bus namespace — all nodes in a group run the same app |
| **Node enrollment** | A physical machine joining the Nebula overlay and one or more device groups |
| **Manager** | The Nebula certificate authority + Gustavo API server |

---

## Installing Gustavo

```bash
pip install gustavo
```

Verify:
```bash
gustavo --help
gustavo manager check
```

---

## Starting the Manager

The manager runs MongoDB (for app/group config) and the Nebula certificate authority as Docker containers on the host:

```bash
gustavo manager up -s mongo      # start MongoDB
# wait ~15 s for MongoDB to initialize
gustavo manager up -s manager    # start Nebula manager + Gustavo API
```

**Health check** (always exits 0 — parse the output):
```bash
gustavo manager check 2>&1 | grep -q "Manager Up" && echo "Ready"
```

This is the pattern used in `gustavo_init.sh` to wait for the manager before registering apps.

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
gustavo apps create -n hello-agent -f hello_agent_config.yaml -d quickstart_subagent
```

`-d quickstart_subagent` sets the default device group for new nodes that enroll with this app.

---

## Device Groups

Device groups map to Messenger bus namespaces. The quickstart creates two:

```bash
# Global coordination bus (Pattern A head)
gustavo device-group create -n quickstart_headagent -a hello-agent

# Local worker bus
gustavo device-group create -n quickstart_subagent -a hello-agent
```

`-a hello-agent` associates the group with the `hello-agent` app so nodes in this group receive that Docker image.

### Adding a node to a device group

```bash
gustavo device-group add-node -n quickstart_subagent --node 10.0.1.42
```

Once added, Gustavo pushes the `hello-agent` image to that node and starts the container.

---

## Node Enrollment

On each edge node, run the Gustavo agent:

```bash
# Download the enrollment script from the manager
curl http://<manager-ip>:8080/enroll.sh | sudo bash

# Or manually
gustavo node enroll \
    --manager <manager-ip>:8080 \
    --groups quickstart_subagent
```

After enrollment, the node:
1. Joins the Nebula overlay network and receives an overlay IP
2. Writes its overlay IP to the `node-aliases` Redis key
3. Receives the `hello-agent` Docker image and starts the container

---

## gustavo_init.sh (quickstart)

The file at `examples/quickstart/gustavo_init.sh` automates the full bootstrap for a single-machine deployment:

```sh
#!/bin/sh
# Full bootstrap: MongoDB → manager → hello-agent app → two device groups
set -e

gustavo manager up -s mongo
sleep 15
gustavo manager up -s manager

until gustavo manager check 2>&1 | grep -q "Manager Up"; do
    echo "[quickstart] Manager not ready, retrying in 5 s..."
    sleep 5
done

# Register hello-agent app (reads REDIS_HOST etc from env)
gustavo apps create -n hello-agent -f /tmp/hello_agent_config.yaml -d quickstart_subagent

# Two device groups — one per Messenger bus
gustavo device-group create -n quickstart_headagent -a hello-agent
gustavo device-group create -n quickstart_subagent  -a hello-agent

tail -f /dev/null   # keep container alive for CLI access
```

---

## Common CLI Commands

```bash
# App management
gustavo apps list
gustavo apps create -n <name> -f <yaml> -d <default-group>
gustavo apps delete -n <name>

# Device groups
gustavo device-group list
gustavo device-group create -n <group> -a <app>
gustavo device-group add-node -n <group> --node <ip>
gustavo device-group remove-node -n <group> --node <ip>
gustavo device-group delete -n <group>

# Nodes
gustavo node list
gustavo node status --node <ip>

# Manager
gustavo manager up -s mongo
gustavo manager up -s manager
gustavo manager check
gustavo manager down
```

---

## Node Identity and Alias Resolution

When `NODE_ADDRESS` is not set, Scarlet agents query the local BackgroundServer which looks up the Nebula overlay IP from Redis:

```
redis HGET node-aliases <hostname> → 10.0.1.42
```

Gustavo populates this during enrollment. As long as the BackgroundServer is running on port 9099, agents get the correct Nebula IP without any static configuration.

See [Node Identity](../concepts/identity.md) for the full resolution chain.
