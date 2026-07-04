<div class="hero">
<h1>Scarlet Composer Studio</h1>
<p class="subtitle">
Distributed shared memory and agent communication for multi-agent systems —
Redis backend, Apache 2.0, built for the edge.
</p>
</div>

<div class="feature-grid">
<div class="feature-card">
<h3>🗺 Mapper</h3>
<p>Distributed key-value store. Workers write independently; any node reads all values with AllGather or folds them with Reduce.</p>
</div>
<div class="feature-card">
<h3>🤝 Federator</h3>
<p>One-line federated aggregation. Workers post local models; the head calls Aggregate to sum, multiply, or max across all contributions.</p>
</div>
<div class="feature-card">
<h3>📬 Messenger</h3>
<p>Reliable per-agent inboxes with sequence-numbered delivery, a liveness registry, and heartbeat threads — all over raw Redis.</p>
</div>
<div class="feature-card">
<h3>🎛 Composer UI</h3>
<p>Streamlit dashboard to deploy scarlets, browse the agent registry, manage data sources, and stream logs — all from a browser.</p>
</div>
<div class="feature-card">
<h3>🤖 LLM / MCP Ready</h3>
<p><code>Messenger.AsTools()</code> exports MCP-compatible tool definitions. Drop into any agent framework: LangChain, LlamaIndex, Open WebUI.</p>
</div>
<div class="feature-card">
<h3>🏭 Edge-First</h3>
<p>Designed for physically distributed IoT and factory-floor deployments. No cloud dependency — just Redis on your network.</p>
</div>
</div>

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
| Deploying to edge nodes with Gustavo | [Gustavo Integration](deployment/gustavo.md) |
| All environment variables | [Environment Variables](deployment/env-vars.md) |
| Full API reference | [API Reference](reference/api.md) |

</div>

---

## Architecture at a Glance

```
┌──────────────────────────────────────────────────────────┐
│                    scarletcomposer                        │
│  Streamlit UI (8501)   Tornado (9099)   scarlet-composer  │
└──────────────────┬────────────────────────────────────────┘
                   │
┌──────────────────▼────────────────────────────────────────┐
│                       Redis                               │
│   Mapper data   Messenger queues   Scarlet definitions    │
└──────────────────▲────────────────────────────────────────┘
                   │
┌──────────────────┴────────────────────────────────────────┐
│                      scarlets                             │
│   Mapper     Federator     Messenger     RedisScarlet      │
│         (agents import directly — no broker)              │
└──────────────────────────────────────────────────────────┘
```

Two packages ship from this repository:

| Package | What it contains |
|---|---|
| `scarlets` | `Mapper`, `Federator`, `Messenger`, `RedisScarlet`, `ScarletBase`, `RedisContract`, `ScarletUtils`, `RedisLogger` |
| `scarletcomposer` | Streamlit UI, Tornado background server, `ScarletInterpreter`, `ScarletHandler`, `scarlet-composer` CLI |

Agent containers only need `scarlets`. The operator dashboard needs `scarletcomposer`.

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

They are complementary. See [positioning_vs_A2A_ACP.md](https://github.com/disys-lab/scarlet-composer-studio/blob/main/proposal/positioning_vs_A2A_ACP.md) for the detailed analysis.

---

## Research

Scarlet Composer Studio was developed at the [DISYS Lab](https://ceat.okstate.edu/iem/people/ramanan-faculty-profile.html), Oklahoma State University, under the [NASA HOME STRI Project](https://homestri.ucdavis.edu/research) (Research Thrust 2) and NSF SaTC Award 2348411.

- [Paritosh Ramanan](https://ceat.okstate.edu/iem/people/ramanan-faculty-profile.html) — Oklahoma State University
- [Nagi Gebraeel](https://www.isye.gatech.edu/users/nagi-gebraeel) — Georgia Tech

Apache License 2.0.
