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

When `NODE_ADDRESS` is not set, the agent queries the local BackgroundServer:

```
GET http://127.0.0.1:9099/api/v2/getNodeInfo
```

The BackgroundServer looks up the current hostname in the `node-aliases` Redis key:

```python
aliases = r.hgetall("node-aliases")   # {"my-hostname": "10.0.1.42"}
node_ip = aliases.get(socket.gethostname())
```

This is how Gustavo-managed deployments work. When Nebula enrolls a node, it writes its overlay IP to `node-aliases`. The agent then discovers its own Nebula IP without any static configuration.

The BackgroundServer endpoint also accepts an alias name:

```
GET http://127.0.0.1:9099/api/v2/getNodeInfo?node=my-hostname
```

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

The `BackgroundServer` (Tornado, port 9099) exposes two endpoints:

| Endpoint | Method | Description |
|---|---|---|
| `/api/v2/getNodeInfo` | GET | Resolve node alias → IP. Query param `node=<hostname>` optional. |
| `/api/v2/getNodeInfo` | POST | Same, body `{"node": "<hostname>"}` |

The Composer UI calls `/api/v2/getNodeInfo` to resolve display names for each agent card.

---

## Composer UI

The Agents page calls `getNodeInfo` for each agent ID it discovers in the Messenger registry. If Nebula aliases are configured, agent cards show stable overlay IPs instead of ephemeral container IPs.

---

## Recommendations

| Scenario | Recommended approach |
|---|---|
| Local dev / Docker Compose | Set `NODE_ADDRESS=local` or `NODE_ADDRESS=127.0.0.1` in `.env` |
| Gustavo-managed edge nodes | Leave `NODE_ADDRESS` unset — Nebula alias resolution handles it |
| Static-IP bare-metal nodes | Set `NODE_ADDRESS` to the machine's LAN IP |
| Kubernetes | Set `NODE_ADDRESS` to the pod's downward API `status.podIP` |
