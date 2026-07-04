# Redis Key Schema

All Redis keys used by Scarlet Composer Studio, in one place.

---

## Mapper / RedisScarlet

| Key pattern | Type | Description |
|---|---|---|
| `{scarletName}_key-value:{key}` | String | Presence marker for a Map entry (value = `"1"`) |
| `{scarletName}_key-value:{key}:0` | Hash | Map entry: fields `updater`, `content` (pickle+zlib bytes), `lastUpdatedTime` |
| `{scarletName}_key-value:{key}:{timestamp}` | Hash | Timeseries entry (when `timeseries=True`): same fields as `:0` |

**Example (scarletName="gradient_bus", key="worker_osu1"):**
```
gradient_bus_key-value:worker_osu1       → "1"
gradient_bus_key-value:worker_osu1:0     → {updater, content, lastUpdatedTime}
```

TTL: `SCARLET_DATA_EXPIRY` seconds (default 3600) set on each write.

---

## Federator

`Federator("model_sync")` creates two internal Mappers:

| Key pattern | Description |
|---|---|
| `model_sync_mapper_reducer_key-value:*` | Per-worker local contributions |
| `model_sync_mapper_global_key-value:global` | Aggregated global result (written by `Aggregate`) |

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
  {name}_key-value:{key}              String  presence marker
  {name}_key-value:{key}:0            Hash    serialized value

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
