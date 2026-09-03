# Node Identity

Every agent needs a stable, unique identity to participate in Messenger buses and appear correctly in the Composer UI. Scarlet Composer resolves the current node's address through a three-step priority chain.

---

## Priority Chain

```
1. NODE_ADDRESS env var          (highest priority — always explicit)
2. BackgroundServer HTTP query   (Gustavo-aware — resolves via Nebula alias)
3. socket.gethostbyname          (fallback — DNS-based local resolution)
```

The first successful result wins. Step 3 is always available and always succeeds (returning a loopback address if nothing else is configured).

---

## Step 1 — Explicit env var

```bash
export NODE_ADDRESS=10.0.1.42
```

Set this on any machine where you know the stable network address in advance. Typical for:
- Docker Compose deployments with fixed bridge IPs
- Edge nodes with static IPs
- CI/test environments

When `NODE_ADDRESS` is set, steps 2 and 3 are skipped entirely.

---

## Step 2 — BackgroundServer / Nebula alias

When `NODE_ADDRESS` is not set, and `MANAGER_HOST`/`MANAGER_PORT` are both
set, the agent queries BackgroundServer at that address (this is
`ScarletBase._resolveNodeAddress()` - see `scarlets/types/ScarletBase.py` -
which is what this whole priority chain actually implements; the harness
project mirrors this same logic in its own `HarnessConfig`):

```
GET http://{MANAGER_HOST}:{MANAGER_PORT}/api/v2/getNodeInfo?app_id={APP_ID}
```

Not a fixed `127.0.0.1:9099` - the target is wherever `MANAGER_HOST`/
`MANAGER_PORT` point, and the one query param the endpoint actually reads
is `app_id`, not `node` (see [Environment Variables](../deployment/env-vars.md)
for these two vars).

The BackgroundServer side (`scarletcomposer/pages/config/BackgroundServer.py`'s
`NodeInfoHandler`) does **not** do a hostname lookup. It resolves the
*caller's own IP* (from `X-Forwarded-For` or the raw socket, same as
`getNodeIp` below), reads the `node-aliases` Redis key as a single **JSON
string** (`json.loads(r.get("node-aliases"))`, not a Hash), and matches
by scanning for the entry whose `hostname` field equals that caller IP:

```python
alias_data = json.loads(r.get("node-aliases"))
for alias, info in alias_data.items():
    if info.get("hostname") == host_ip:
        node_address, device_group = alias, info.get("device_group")
```

This is how Gustavo-managed deployments work. When Nebula enrolls a node, it writes its overlay IP to `node-aliases`. The agent then discovers its own Nebula IP without any static configuration.

If `device_group` is still unresolved after that lookup, and
`MANAGER_CONTAINER_HOST`/`MANAGER_CONTAINER_PORT`/`MANAGER_CONTAINER_AUTH_TOKEN`
are set (a separate env-var trio from `MANAGER_HOST`/`MANAGER_PORT` above -
this one configures BackgroundServer's *own* upstream call to the real
Nebula manager, not how the agent reaches BackgroundServer), it queries
Nebula directly for the app's `device_group`.

---

## Step 3 — DNS fallback

If the BackgroundServer is not running or the hostname has no alias, the agent falls back to:

```python
socket.gethostbyname(socket.gethostname())
```

This returns the machine's primary IP as seen by the OS. On a developer laptop with no Nebula overlay this typically returns `127.0.0.1` or the LAN IP.

---

## How Agent IDs Are Formed

```python
NODE_ADDRESS = resolve()   # priority chain above
AGENT_ID = f"{APP_ID}_{NODE_ADDRESS}"
# APP_ID=quickstart, NODE_ADDRESS=10.0.1.42 → "quickstart_10.0.1.42"
```

The `AGENT_ID` becomes:
- The `agentId` passed to `Messenger` — determines which inbox the agent reads
- The key used in `GatherStatus` responses
- The label shown in the Composer UI agent cards

---

## BackgroundServer Endpoints

The `BackgroundServer` (Tornado — same class scarletcomposer has always
used, `scarletcomposer/pages/config/BackgroundServer.py`, now run as its
own `background-server` service via `docker/composer-app/background_server.py`
rather than bundled into the composer container's own process set; default
port `9098`, configurable via `BACKGROUND_SERVER_PORT` — see
[Docker Images](../deployment/docker.md#node-identity-resolution-background-server))
exposes two endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v2/getNodeIp` | GET | Returns `{"host_ip": "<caller's resolved IP>"}` - no params. |
| `/api/v2/getNodeInfo` | GET | Resolves the *caller's own IP* against the `node-aliases` map. Optional query param `app_id=<APP_ID>`, used only to also look up `device_group` from Nebula if the alias map doesn't already have one. Returns `{"host_ip", "node_address", "device_group"}`. There is no `node=` param - passing one has no effect. |

---

## Composer UI

The Agents page does **not** call `getNodeInfo` itself - agent cards just
display whatever `agent_id` string is already in the Messenger registry
record (`{APP_ID}_{NODE_ADDRESS}`, per "How Agent IDs Are Formed" above).
`getNodeInfo` is resolved once, by each *agent process itself* at
startup - if Nebula aliases are configured, that's what makes the
resolved `NODE_ADDRESS` (and therefore the `agent_id` the UI displays) a
stable overlay alias instead of an ephemeral container IP, not anything
the UI does at render time.

---

## Recommendations

| Scenario | Recommended approach |
|---|---|
| Local dev / Docker Compose | Set `NODE_ADDRESS=local` or `NODE_ADDRESS=127.0.0.1` in `.env` |
| Gustavo-managed edge nodes | Leave `NODE_ADDRESS` unset — Nebula alias resolution handles it |
| Static-IP bare-metal nodes | Set `NODE_ADDRESS` to the machine's LAN IP |
| Kubernetes | Set `NODE_ADDRESS` to the pod's downward API `status.podIP` |
