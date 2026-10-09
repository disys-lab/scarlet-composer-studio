# scarlet-agentic-harness

A generalized decentralized agentic **Skill** harness built on top of this
repo's `scarlets` primitives (`Mapper`, `Federator`, `Messenger`) — deployed
alongside [Gustavo](https://github.com/disys-lab/gustavo) as
`ghcr.io/disys-lab/scarlet-agents`.

Full docs, including core concepts, getting started, and deployment
instructions, now live in this repo's MkDocs site:
[docs/harness/](../docs/harness/index.md) (or the hosted site's **Harness**
nav section).

## Running the tests

This is the one path from a fresh clone to a green suite. Run it from the
**repository root**, not from `harness/` - two of the three installs are
of sibling packages.

```bash
# 1. A virtualenv on a Python the wheels exist for. 3.11-3.13; CI tests
#    3.9-3.11. Avoid the newest release: pandas and friends have no
#    prebuilt wheels for it yet and pip falls back to compiling from
#    source, which fails.
python3.13 -m venv harness/.venv
source harness/.venv/bin/activate

# 2. `scarlets` is built FROM THIS REPO, not downloaded. requirements.txt
#    lists it by name, so without this step pip searches PyPI, finds
#    nothing, and the install dies at "No matching distribution found for
#    scarlets".
pip install -e .
pip install dist/data_connectors-*.whl

# 3. The harness itself, plus its test dependencies.
pip install -e harness/ -r harness/requirements.txt

# 4. `composer-api` is not a package - tests/test_query_data_source.py
#    imports `config_store` from it directly.
export PYTHONPATH="$PWD/composer-api"

python -m pytest harness/tests/ -v
```

Expect **478 passed, 15 skipped, 1 failed**. The skips are the
multi-process tests, which need an LLM endpoint because every skill
generates its worker-local SQL with a model - set `LLM_BASE_URL`,
`LLM_API_KEY` and `LLM_MODEL` and they run too (497 passed, 1 failed).
The one failure is a broker wiring issue; see docs/AGENTS.md. The
Postgres fixture is also intermittently flaky and can take 4 more with
it.

A handful of tests are known to fail on a fresh clone; they rotted during
a period when nobody could run them. See the "known failures" note in
docs/AGENTS.md before assuming you broke something.
