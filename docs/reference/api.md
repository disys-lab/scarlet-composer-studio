# API Reference

Full API documentation covering every class, method, parameter, return type, and Redis key schema.

---

## Quick Index

### `scarlets` package

| Class | Module | Purpose |
|---|---|---|
| `ScarletBase` | `scarlets.types.ScarletBase` | Base class — env vars, Redis client, OPS constants |
| `RedisScarlet` | `scarlets.types.RedisScarlet` | Low-level Push / Pull / Clear |
| `Mapper` | `scarlets.core.Mapper` | Distributed key-value: Map / AllGather / Reduce |
| `Federator` | `scarlets.formulations.Federator` | Federated aggregation: Map + Aggregate |
| `Messenger` | `scarlets.messaging.Messenger` | Per-agent inboxes: Send / Receive / Broadcast |
| `ContractBase` | `scarlets.types.ContractBase` | Abstract contract base |
| `RedisContract` | `scarlets.types.RedisContract` | Contract with Redis persistence |
| `ScarletUtils` | `scarlets.utils.ScarletUtils` | Serialisation helpers (pickle + zlib) |
| `RedisLogger` | `scarlets.utils.RedisLogger` | Structured logging to Redis |

### `scarletcomposer` package

| Class / Function | Module | Purpose |
|---|---|---|
| `ScarletInterpreter` | `scarletcomposer.interpreter.ScarletInterpreter` | Parse `#scarlet` declarations from source files |
| `BackgroundServer` | `scarletcomposer.pages.config.BackgroundServer` | Tornado server: `/api/v2/getNodeInfo`, `/api/v2/getNodeIp` |
| `scarletDriver` CLI | `scarletcomposer.composer.scarletDriver` | `scarlet-composer` CLI entry point — see [CLI Reference](cli.md) |

### `composer-api` (FastAPI) — the operator dashboard's real HTTP API

| Router | Path prefix | Purpose |
|---|---|---|
| `auth` | `/api/auth` | Session login/logout (Nebula-backed, when `AUTH_ENABLED`) |
| `dashboard` | `/api/dashboard` | Redis health, agent/scarlet counts |
| `agents` | `/api/agents` | Live agent registry from `GatherStatus()` |
| `scarlets` | `/api/scarlets` | Registered scarlet definitions; interpret/deploy from uploaded source |
| `data-sources` | `/api/data-sources` | The centralized data-source broker registry |
| `logs` | `/api/logs` | Live tail of the `RedisLogger` stream |
| `config` | `/api/config` | Persisted composer-api configuration |

`composer-ui` (Next.js) is the browser client for this API — see [Composer UI](../composer/index.md).

### `harness` (`scarlet_agentic_harness`) — the agentic `Skill` runtime

See [Harness → Core Concepts](../harness/concepts.md) for the `Skill` interface, dispatch, and `AgentDialogue`; the reference skills live under `harness/scarlet_agentic_harness/skills/`.

---

For parameter signatures, return types, and code examples, see the source docstrings in each package.
