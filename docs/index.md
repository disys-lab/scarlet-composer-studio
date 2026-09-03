<div class="hero">
<h1>Scarlet Composer Studio</h1>
<p class="subtitle">
Distributed shared memory and communication primitives for decentralized Agentic-AI —
Redis backend, Apache 2.0, built for the edge.
</p>
</div>

| Component | What it does |
|---|---|
| **Mapper** | Distributed key-value store. Workers write independently; any node reads all values with `AllGather` or folds them with `Reduce`. |
| **Federator** | One-line federated aggregation. Workers post local models; the head calls `Aggregate` to sum, multiply, or max across all contributions. |
| **Messenger** | Reliable per-agent inboxes with sequence-numbered delivery, a liveness registry, and heartbeat threads — all over raw Redis. |
| **Harness** | A decentralized `Skill` runtime built on the primitives above: a head dispatches work, workers coordinate, and agents find each other's data by feature, not by connection string. |
| **Composer UI** | Operator dashboard to deploy scarlets, browse the agent registry, manage data sources, and stream logs — from a browser. |
| **LLM / MCP ready** | `Messenger.AsTools()` exports MCP-compatible tool definitions. Drop into any agent framework: LangChain, LlamaIndex, Open WebUI. |

Designed for physically distributed, edge-first deployments — industrial and IoT sites with no cloud dependency, just Redis on your own network.

---

## Quick Links

<div class="quick-links" markdown>

| Goal | Where to go |
|---|---|
| Running in 5 minutes | [Quickstart (Docker Compose)](quickstart.md) |
| Understanding the primitives | [Scarlet Primitives](concepts/scarlets.md) |
| Two buses per agent explained | [Two-Channel Architecture](concepts/two-channel.md) |
| Multiple campaigns on one deployment | [Campaign Isolation](concepts/campaigns.md) |
| Connecting to LangChain / Open WebUI | [LLM / MCP Integration](guides/llm-integration.md) |
| Building a decentralized agent (`Skill`, dispatch, dialogue) | [Harness](harness/index.md) |
| Deploying to edge nodes with Gustavo | [Gustavo Integration](deployment/gustavo.md) |
| All environment variables | [Environment Variables](deployment/env-vars.md) |
| Full API reference | [API Reference](reference/api.md) |

</div>

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────────┐
│  scarlet-composer  (operator UI)                              │
│  composer-ui (Next.js, :3000)  ⇄  composer-api (FastAPI)       │
│  background-server — node identity resolution                 │
└───────────────────────────────┬────────────────────────────────┘
                                │
┌───────────────────────────────▼────────────────────────────────┐
│                             Redis                              │
│      Mapper data     Messenger queues     Scarlet definitions   │
└───────────────────────────────▲────────────────────────────────┘
                                │
┌───────────────────────────────┴────────────────────────────────┐
│  scarlet-agents  (harness)              scarlets  (library)     │
│  Skill dispatch, AgentDialogue,         Mapper / Federator /    │
│  local-first data access                Messenger — imported    │
│                                          directly, no broker     │
└──────────────────────────────────────────────────────────────┘
```

Four packages ship from this repository:

| Package | What it contains |
|---|---|
| `scarlets` | `Mapper`, `Federator`, `Messenger`, `RedisScarlet`, `ScarletBase`, `RedisContract`, `ScarletUtils`, `RedisLogger` |
| `scarletcomposer` | `composer-api` (FastAPI) + `composer-ui` (Next.js) operator dashboard, `ScarletInterpreter`, `scarlet-composer` CLI |
| `data-connectors` | Pluggable data-source connectors (MSSQL, Postgres, MySQL, PI, InfluxDB, Redis, CSV, Excel) |
| `harness/` | The agentic `Skill` runtime — see [Harness](harness/index.md) |

Agent containers only need `scarlets`. The operator dashboard needs `scarletcomposer`. Agents built with the harness also need `data-connectors` for local-mode data sources.

---

## vs. A2A and ACP

A2A and ACP answer: *how does one agent call another?*

Scarlet Composer answers: *how do many agents share state and coordinate across machines they physically own?*

| | A2A / ACP | Scarlet Composer |
|---|---|---|
| Model | Request-response (HTTP) | Shared memory + messaging |
| Topology | Point-to-point | Many-to-many via shared primitives |
| State | Stateless | Persistent in Redis |
| Aggregation | Manual (N HTTP round trips) | `AllGather` / `Reduce` built in |
| Data sovereignty | Cloud-mediated | Operator-controlled |
| LLM integration | Yes | Yes — `AsTools()` / MCP |

They are complementary.

---

## Research

Scarlet Composer Studio was developed at the [DISYS Lab](https://ceat.okstate.edu/iem/people/ramanan-faculty-profile.html), Oklahoma State University, under the [NASA HOME STRI Project](https://homestri.ucdavis.edu/research) (Research Thrust 2) and NSF SaTC Award 2348411.

- [Paritosh Ramanan](https://ceat.okstate.edu/iem/people/ramanan-faculty-profile.html) — Oklahoma State University
- [Nagi Gebraeel](https://www.isye.gatech.edu/users/nagi-gebraeel) — Georgia Tech

Apache License 2.0.
