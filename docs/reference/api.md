# API Reference

Every class, method, and function below links to a page generated directly from that package's source docstrings — not a hand-maintained copy, so it can't drift out of sync with the code.

- **[Scarlets API](scarlets-api.md)** — `Mapper`, `Federator`, `Messenger`, and the base/contract/utility classes underneath them.
- **[Harness API](harness-api.md)** — the `Skill` interface, all 8 reference skills, `HarnessContext`, dispatch (`head`/`worker`), communication (`buses`/`dialogue`/`router`), cancellation/observability, and LLM integration.
- **[Data Connectors API](data-connectors-api.md)** — the `Connector` base interface and all 8 connector implementations (mssql, postgres, mysql, pi, influx, redis, csv, excel).

---

## Quick Index

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
