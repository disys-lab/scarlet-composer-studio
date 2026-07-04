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
| `ScarletHandler` | `scarletcomposer.handlers.ScarletHandler` | Streamlit component for managing scarlets |
| `ScarletInterpreter` | `scarletcomposer.interpreter.ScarletInterpreter` | Parse `#scarlet` declarations from source files |
| `BackgroundServer` | `scarletcomposer.server.BackgroundServer` | Tornado server: `/api/v2/getNodeInfo` |
| `Sidebar.sidebarInit` | `scarletcomposer.components.Sidebar` | Render and persist connection settings sidebar |
| `loadSidebarCss` | `scarletcomposer.components.loadSidebarCss` | Inject custom CSS |
| `agents_page` | `scarletcomposer.pages.Agents` | Agents tab renderer |
| `data_sources_page` | `scarletcomposer.pages.DataSources` | Data Sources tab renderer |
| `Logging` page | `scarletcomposer.pages.Logging` | Logging tab renderer |
| `scarletDriver` CLI | `scarletcomposer.cli.scarletDriver` | `scarlet-composer` CLI entry point |

---

For parameter signatures, return types, and code examples, see the source docstrings in the `scarlets` and `scarletcomposer` packages.
