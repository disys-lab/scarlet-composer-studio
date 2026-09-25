# Contributing

Contributions are welcome — bug reports, documentation improvements, new examples, and feature additions.

---

## Development Setup

```bash
git clone https://github.com/disys-lab/scarlet-composer-studio
cd scarlet-composer-studio

# Install both packages in editable mode - `pip install -e .` alone only
# picks up ./setup.py (scarlets); scarletcomposer needs its own setup file
# named explicitly.
python3 setup.py develop
python3 setup_composer.py develop

# Install test dependencies
pip install pytest requests
```

Set environment variables for your development Redis:

```bash
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_AUTH_TOKEN=your-dev-password
```

---

## Running Tests

The test suite requires a running Redis instance and the mock Nebula manager. Start both with Docker Compose:

```bash
docker compose -f tests/docker-compose.yml up -d
./run_tests.sh
```

Or run specific tests:

```bash
pytest tests/test_e2e.py -v
pytest tests/test_scarlets.py -v
pytest tests/test_background_server.py -v
```

All 20+ e2e tests must pass before opening a pull request.

### Test structure

| File | What it tests |
|---|---|
| `tests/test_e2e.py` | Full agent lifecycle — registration, task dispatch, ordered delivery, broadcast, GatherStatus, clearAll |
| `tests/test_scarlets.py` | Mapper and Federator primitives |
| `tests/test_background_server.py` | Tornado `/api/v2/getNodeInfo` resolution |
| `tests/test_data_sources.py` | Data source UI logic |

---

## Repository Structure

```
scarlet_composer_studio_open_source/
├── scarlets/                # pip package: scarlets (agent primitives)
│   ├── core/Mapper.py
│   ├── formulations/Federator.py
│   ├── messaging/Messenger.py
│   ├── types/
│   │   ├── ScarletBase.py
│   │   └── RedisScarlet.py
│   ├── contract/RedisContract.py
│   └── utils/
│       ├── ScarletUtils.py
│       └── RedisLogger.py
│
├── scarletcomposer/         # pip package: scarletcomposer (CLI + legacy Streamlit pages)
│   ├── composer/
│   │   ├── scarletDriver.py    # CLI entry point
│   │   ├── ScarletHandler.py   # deploy pipeline
│   │   └── ScarletInterpreter.py
│   └── pages/                  # Streamlit-era - not the deployed UI (see composer-ui/ below),
│       │                       # kept because docker/composer-app/background_server.py still
│       │                       # imports from here
│       ├── Agents.py
│       ├── DataSources.py
│       ├── Logging.py
│       └── config/
│           ├── BackgroundServer.py
│           └── Sidebar.py
│
├── composer-api/            # FastAPI backend for the deployed Composer UI
├── composer-ui/             # Next.js frontend for the deployed Composer UI
│
├── harness/                 # scarlet_agentic_harness - decentralized agentic Skill runtime
├── data_connectors/         # pip package: data-connectors (mssql/postgres/pi/influx/csv/...)
├── broker/                  # standalone broker process for mode: broker data sources
│
├── docker/
│   ├── agent-base/Dockerfile    # scarlet-agent-base image
│   └── composer-app/Dockerfile  # scarlet-composer image (composer-api + composer-ui combined)
│
├── examples/
│   └── quickstart/          # Docker Compose quickstart with hello-agent
│
├── tests/
│   ├── conftest.py
│   ├── docker-compose.yml   # test infrastructure (Redis + mock manager)
│   ├── mock_manager/
│   ├── test_e2e.py
│   └── ...
│
├── docs/                    # this site - see docs/reference/api.md for the full page map
│
├── setup.py             # scarlets package
├── setup_composer.py    # scarletcomposer package
├── setup_connectors.py  # data-connectors package
└── requirements.txt
```

---

## Pull Request Guidelines

- Open an issue first for significant feature additions or breaking changes.
- Match the coding style of the file you are modifying.
- Add or update tests for any changed behaviour. All existing tests must continue to pass.
- Keep commits focused. One logical change per commit.
- User-facing documentation lives under `docs/` (nested by topic — `concepts/`, `guides/`, `deployment/`, `composer/`, `harness/`, `reference/`) - see `mkdocs.yml`'s `nav` for the full page map.

---

## Reporting Bugs

Open a GitHub issue with:
- Python version and OS
- Scarlet package version (`pip show scarlets`)
- Minimal reproduction script
- Full traceback

---

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
