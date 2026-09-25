# Redis Key Schema

All Redis keys used by Scarlet Composer Studio, in one place.

---

## Mapper / RedisScarlet

| Key pattern | Type | Description |
|---|---|---|
| `{scarletName}_key-list` | Set | Registry of every currently-live logical key. One member added per `Map` call - plain and `timeseries=True` both, unconditionally. |
| `{scarletName}_key-value:{key}:0` | Hash | Map entry: fields `updater`, `content` (pickle+zlib bytes), `lastUpdatedTime`. Chunk index is always `0` - there's no per-key chunking currently. |

A `timeseries=True` call appends a `#{timestamp}` suffix to `key` before writing, so each tick becomes its own independent registry member and chunk hash rather than overwriting the last one.

**Example (scarletName="gradient_bus"):**
```
# plain Map("worker_osu1", ...)
gradient_bus_key-list                          → {"worker_osu1", "worker_osu2#1758649200"}
gradient_bus_key-value:worker_osu1:0           → {updater, content, lastUpdatedTime}

# timeseries Map("worker_osu2", timeseries=True) at time.time() == 1758649200
gradient_bus_key-value:worker_osu2#1758649200:0 → {updater, content, lastUpdatedTime}
```

`@` and `:` are rejected outright in a caller-supplied `key` (raises `Exception`) - both are reserved by this scheme's own delimiters (`:` between key/chunk, `#` between a timeseries key and its timestamp).

TTL: chunk hashes get `SCARLET_DATA_EXPIRY` seconds (default 3600) on each write. **`{scarletName}_key-list` itself has no TTL** - a member whose chunk has already expired is only pruned lazily, the next time `getMapperLength()` runs (it checks each member's chunk with `EXISTS` and `SREM`s any that are gone). Until something calls `getMapperLength()` again, an expired key can still appear as "registered" with nothing behind it.

---

## Federator

`Federator("model_sync")` creates two internal Mappers:

| Key pattern | Description |
|---|---|
| `model_sync_mapper_reducer_key-list` / `model_sync_mapper_reducer_key-value:{worker_key}:0` | Per-worker local contributions - an ordinary Mapper underneath, see above |
| `model_sync_mapper_global_key-list` / `model_sync_mapper_global_key-value:global:0` | Aggregated global result (written by `Aggregate`, always under the fixed key `"global"`) |

---

## Messenger

| Key pattern | Type | Description |
|---|---|
| `{scarletName}:msg:tail:{agentId}` | String (int) | Next sequence number for messages to `agentId` |
| `{scarletName}:msg:head:{agentId}` | String (int) | Last acknowledged sequence number for `agentId`'s inbox |
| `{scarletName}:msg:{agentId}:{seq}` | String (JSON) | Message: fields `from`, `to`, `seq`, `body`, `ts`, `instance_id` |
| `{scarletName}:reg:{agentId}` | String (JSON) | Liveness registry: `agent_id`, `instance_id`, `status`, `ts`, `capabilities` |

**Example (scarletName="quickstart_headagent", agentId="hello-agent_local"):**
```
quickstart_headagent:msg:tail:hello-agent_local   → "5"
quickstart_headagent:msg:head:hello-agent_local   → "3"
quickstart_headagent:msg:hello-agent_local:4      → {from, to, seq, body, timestamp}
quickstart_headagent:reg:hello-agent_local        → {status, last_seen, capabilities, ...}
```

The `head` pointer being 3 when `tail` is 5 means messages 4 and 5 are unread.

---

## Scarlet Definitions

| Key pattern | Type | Description |
|---|---|
| `scarlet_definition_{scarletName}` | Hash | Self-registration record: `scarlet_type`, `name`, `description`, `created_by`, `created_at` |

Written by `register_scarlet_definition()` in `ScarletBase`. `overwrite=False` by default — first caller wins.

---

## Data Sources (Three-Tier Registry)

| Key | Type | Description |
|---|---|---|
| `data-sources:global` | Hash | Campaign-agnostic named data sources |
| `data-sources:worker:{APP_ID}` | Hash | Campaign-scoped data sources |
| `data-sources:local:{NODE_ADDRESS}` | Hash | Node-local data sources |

Each hash field name is the data source name; the value is a JSON string.

---

## Node Aliases (Gustavo / Nebula)

| Key | Type | Description |
|---|---|---|
| `node-aliases` | Hash | Maps hostname → Nebula overlay IP. Written by Gustavo at node enrollment. |

Read by `BackgroundServer.NodeInfoHandler` to resolve the caller's overlay IP.

---

## Logging

| Key pattern | Type | Description |
|---|---|---|
| `logs_{uuid4}` | Hash | One log entry per key. Fields: `time`, `app`, `node`, `file`, `filename`, `line`, `level`, `msg`. |

Written by `RedisLogger.setRedisLog()`. Keys expire after `RedisLogger.expiry_time` seconds (default 600 s). The Composer UI scans for `logs_*` keys and reads `app` / `node` fields for filter dropdowns.

---

## Summary Table

```
Mapper
  {name}_key-list                     Set     registry of live logical keys (no TTL)
  {name}_key-value:{key}:0            Hash    serialized value (TTL'd)

Messenger
  {name}:msg:tail:{id}                String  write cursor
  {name}:msg:head:{id}                String  read cursor
  {name}:msg:{id}:{seq}               Hash    one message
  {name}:reg:{id}                     Hash    liveness record

Scarlet registry
  scarlet_definition_{name}           Hash    type/desc/created_by

Data sources
  data-sources:global                 Hash    global tier
  data-sources:worker:{APP_ID}        Hash    campaign tier
  data-sources:local:{NODE_ADDRESS}   Hash    node tier

Node aliases
  node-aliases                        Hash    hostname→Nebula IP

Logging
  logs_{uuid}                         Hash    one entry: time/app/node/level/msg/file/line
```
