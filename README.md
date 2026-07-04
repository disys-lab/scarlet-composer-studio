# Scarlet Composer Studio

Distributed shared memory and agent communication for multi-agent systems — Redis backend, Apache 2.0, built for the edge.

**[Full documentation →](https://disys-lab.github.io/scarlet-composer-studio/)**

---

## Packages

| Package | Install | Contents |
|---|---|---|
| `scarlets` | `pip install scarlets` | `Mapper`, `Federator`, `Messenger`, `RedisScarlet`, `ScarletBase`, `RedisLogger` |
| `scarletcomposer` | `pip install scarletcomposer` | Streamlit UI, Tornado server, `ScarletInterpreter`, `scarlet-composer` CLI |

Agent containers only need `scarlets`. The operator dashboard needs `scarletcomposer`.

---

## Quick Start

```bash
git clone https://github.com/disys-lab/scarlet-composer-studio
cd scarlet-composer-studio/examples/quickstart
cp .env.example .env   # set REDIS_HOST and REDIS_AUTH_TOKEN
docker compose up --build -d
```

Open **http://localhost:8501** — the Composer UI. See the [Quickstart guide](https://disys-lab.github.io/scarlet-composer-studio/quickstart/) for a step-by-step walkthrough.

---

## The Three Primitives

```python
from scarlets.core.Mapper import Mapper
from scarlets.formulations.Federator import Federator
from scarlets.messaging import Messenger
import numpy as np

# Mapper — distributed key-value, any Python object
m = Mapper("gradient_bus")
m.Map(np.array([0.1, 0.2, 0.3]), key="worker_osu1")
values, ok, _ = m.AllGather()

# Federator — federated aggregation (FedAvg pattern)
fdr = Federator("model_sync", op=Mapper.SUM)
fdr.Map(local_weights, key="worker_1")
global_weights, ok, _ = fdr.Aggregate(np.zeros(128))

# Messenger — reliable per-agent inboxes
bus = Messenger("quickstart_headagent", agentId="my_agent")
bus.Send("worker_1", {"task": "run_inference"})
reply = bus.Receive(timeout=5)
```

---

## Documentation

- **[Architecture](https://disys-lab.github.io/scarlet-composer-studio/concepts/scarlets/)** — Scarlet primitives, Redis key schema, two-channel design
- **[Quickstart](https://disys-lab.github.io/scarlet-composer-studio/quickstart/)** — Docker Compose, 5 minutes
- **[Deployment](https://disys-lab.github.io/scarlet-composer-studio/deployment/gustavo/)** — Gustavo integration, multi-node edge
- **[LLM / MCP Integration](https://disys-lab.github.io/scarlet-composer-studio/guides/llm-integration/)** — `Messenger.AsTools()`, LangChain, Open WebUI
- **[Full API Reference](https://disys-lab.github.io/scarlet-composer-studio/reference/api/)** — every class, method, parameter, Redis key

---

## Research

Developed at the [DISYS Lab](https://ceat.okstate.edu/iem/people/ramanan-faculty-profile.html), Oklahoma State University, under the [NASA HOME STRI Project](https://homestri.ucdavis.edu/research) (Research Thrust 2) and NSF SaTC Award 2348411.

- [Paritosh Ramanan](https://ceat.okstate.edu/iem/people/ramanan-faculty-profile.html) — Oklahoma State University
- [Nagi Gebraeel](https://www.isye.gatech.edu/users/nagi-gebraeel) — Georgia Tech

Apache License 2.0.
