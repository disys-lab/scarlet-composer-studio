# Design decisions worth knowing

- **Env var vocabulary matches `scarlet_composer_agentic_design/DESIGN_v3.md`
  §15 exactly** (`REDIS_HOST`/`PORT`/`AUTH_TOKEN`, `APP_ID`, `NODE_ADDRESS`,
  `DEVICE_GROUP`, `HEAD_BUS`) — this harness is meant to be a drop-in
  Gustavo app, not a parallel identity system. `ROLE` and `LLM_*` are new;
  they don't exist in scarlet-composer-studio itself.
- **Capability reporting shape matches DESIGN_v3.md §8.3** exactly
  (`status`/`role`/`capabilities`/`data_sources`/`mcp_tools`/`device_group`/
  `node_address`) so agents built with this harness show up correctly in
  scarlet-composer-studio's own Agents dashboard, not just to each other.
- **`Skill.coordinator_for()` defaults to a random worker, never the head.**
  Nothing about `Mapper`/`Federator` requires the head to call
  `AllGather()`/`Aggregate()` itself — that's an application-level choice,
  and defaulting to the head would make it a bottleneck for every skill's
  aggregation step under concurrent invocations, not just dispatch. The head
  retains control over task *routing* (DESIGN_v3.md §8.5); that's a
  different thing from being where computation happens. A skill can still
  override `coordinator_for()` to return `ctx.agent_id` when the aggregation
  is cheap enough that the extra two message hops aren't worth it — an
  explicit opt-in, not the default.
- **A worker never runs its own LLM call for a well-defined skill.** Once
  the head has decided which skill applies, the message it sends is already
  fully structured — re-interpreting it with another LLM call on the worker
  side would just reintroduce ambiguity one hop later. Worker-side dispatch
  is a plain deterministic lookup (`worker.handle_message`).
- **One Docker image, role picked by `ROLE` env var** is the packaging
  convention (see [Deployment](deployment.md)) — same spirit as
  scarlet-composer-studio's own `APP_ID`/`DEVICE_GROUP` pattern. Keeps the
  skill library identical on head and worker by construction; no
  version-skew risk between two images.
- **`MessageRouter` (`router.py`) is now the sole caller of `Receive()`** on
  every bus, via `Buses.global_router`/`local_router` — nothing else may
  call `global_bus.Receive()`/`local_bus.Receive()` directly. This isn't
  stylistic: scarlets' `Messenger` transport has no way to filter or peek
  without consuming, so any second independent caller of `Receive()` on the
  same bus races the first and can permanently lose a message meant for it.
  The router demultiplexes by `request_id`; skills call
  `ctx.buses.local_router.receive_for(request_id, timeout)` instead of
  `ctx.buses.local_bus.Receive(timeout)`, and must call `.forget(request_id)`
  once done (success or error) since queues are keyed by UUID and never
  auto-expire.
- **Local-first data access**: site-owned config
  (`~/.scarlet/config.yaml`, see `local_config.py`) is the primary
  mechanism for a worker's own data sources, not the centralized
  composer-api broker registry — that stays available for genuinely
  centralized sources, unchanged. Coordination between agents happens at
  the *feature/tag* level ("who can supply Roll Speed"), not the
  *infrastructure* level ("who has a postgres connection to host X") — the
  head or any requesting agent never needs to know or care what connector
  type backs a given tag. See the `query_feature` skill and
  `AgentDialogue`'s `context_fn` (tag discovery is peer-to-peer and
  semantic, not a central lookup).
