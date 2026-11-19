# Quickstart

Bring up a head, four workers and a notebook server, then ask the fleet a
question in plain English. About five minutes, most of it image build.

## What you need

- Docker with Compose
- An OpenAI-compatible LLM endpoint (base URL, API key, model name). Any
  server speaking the chat-completions API works.

## 1. Configure

Create `.env` beside the compose file:

```bash
REDIS_AUTH_TOKEN=choose-anything
LLM_BASE_URL=https://your-endpoint/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
```

Nothing else is required. The harness derives bus names and agent ids from
`APP_ID` and `NODE_ADDRESS`, which the compose file already sets.

## 2. Build and start

```bash
docker build -f harness/Dockerfile -t scarlet-agents:local .
docker compose --profile agents up -d
```

That gives you Redis, a head, four workers, the Composer UI and Jupyter.
Check they are all live:

```bash
docker compose ps
```

## 3. Give the workers some data

Each worker reads `~/.scarlet/config.yaml` and nothing else - no path is
ever passed in by the head:

```yaml
sources:
  - name: turbine_vibration
    type: csv
    mode: local
    path: /data/plant_alpha/turbine.csv
    description: "80 rows. Columns: vibration_rms, bearing_temp_c, power_kw"
```

Workers profile their sources at boot: row counts, numeric columns, and
temporal columns with their format. Notebook 06 and later generate this
layout for you, with a different shape per worker.

## 4. Ask it something

Open Jupyter (the compose file maps it to `localhost:8888`) and run the
notebooks in order. They build on each other:

| Notebook | What it shows |
|---|---|
| 01-05 | The primitives alone: Messenger, Mapper, Federator. No LLM. |
| 06 | First LLM agent: a variance across workers from a plain-English question. |
| 07-09 | Routing, an anomaly ensemble, and self-healing under worker failure. |
| 10-12 | The same, over vectors and matrices rather than scalars. |
| 13 | Aggregating over a subset of workers. |
| 14 | One call, a whole computation - compound skills. |
| 15 | Asking for a slice of time - row filtering. |

The shortest path to seeing it work is 06. To ask directly rather than
through a notebook:

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async with streamable_http_client("http://agent-head:8090/mcp") as (r, w):
    async with ClientSession(r, w) as session:
        await session.initialize()
        result = await session.call_tool("ask_scarlet_agent", {
            "message": "What is the mean power across the fleet?"})
        print(result.content[0].text)
```

Note what the question does **not** say: no source, no file, no column, no
SQL. Each worker resolves its own.

## 5. Watch it think

The Composer UI (`localhost:3000`) lists conversations, the skills each
one invoked, and the head's reasoning as it goes. Useful when an answer
looks wrong and you want to know which step produced it.

## Running the tests

```bash
docker run --rm -v "$PWD/harness/tests:/app/tests:ro" -w /app \
  scarlet-agents:local \
  sh -c "pip install -q pytest pyyaml && python -m pytest tests/ -q"
```

Some tests need Redis and Postgres fixtures and will error without them;
the rest run anywhere.

## Troubleshooting

**"no online worker currently reports the X capability"** - the workers
have not registered yet, or they booted without that skill. Give them a
few seconds, then check `docker compose logs agent-worker1`.

**The Composer shows no conversations** - check
`/api/conversations?bus=<your-head-bus>` directly. A 500 there means one
stored message could not be serialised, and the listing is all-or-nothing.

**A notebook cell times out** - the head's conversation is longer than the
cell's limit, usually because it is retrying. The head's logs name the
skill and the reason.

## Next

- [Architecture](architecture.md) - what each module does
- [Core Concepts](concepts.md) - head/worker split, the `Skill` contract
- [AGENTS.md](../AGENTS.md) - contributing a skill of your own
