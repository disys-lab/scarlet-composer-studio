# scarlet-notebooks-agents tutorial image — extends scarlet-agents, used
# for all three containers this tutorial launches (head + both workers),
# not just the workers despite the directory name.
#
# Two independent fixes on top of the published scarlet-agents image:
#
# 1. duckdb + pandas, for CsvConnector (data_connectors' own declared
#    dependency, installed --no-deps in the published image - see
#    harness/Dockerfile's own comment on that). Only the workers actually
#    use this.
#
# 2. pyyaml - NOT tutorial-specific. Confirmed by running the real
#    published ghcr.io/disys-lab/scarlet-agents:latest image directly:
#    `local_config.py` does `import yaml` at module level, imported via
#    buses.py on every single startup regardless of ROLE - the published
#    image crash-loops in any role, head or worker, with
#    ModuleNotFoundError: No module named 'yaml'. This is a real,
#    pre-existing bug in harness/Dockerfile itself, not something this
#    tutorial introduced - flagged separately, worth fixing there too so
#    every other consumer of that image isn't silently broken the same
#    way. Included here as a local workaround so this tutorial runs
#    correctly against today's published image regardless of whether/when
#    that fix lands upstream.
#
# Tutorial-only: built locally by notebook 06 itself via the Docker SDK,
# never published.
ARG AGENTS_VERSION=latest
FROM ghcr.io/disys-lab/scarlet-agents:${AGENTS_VERSION}

RUN pip install --no-cache-dir "duckdb>=1.0.0" "pandas>=2.0.0" "pyyaml>=6.0"

# local_data.py's CSV_PATH support (this repo's own
# harness/scarlet_agentic_harness/skills/local_data.py) is source-only
# right now - the published scarlet-agents:latest image was built before
# that change existed, so it has none of it baked in. Overwriting it here
# is a duplicate of that same file, kept in sync by hand for now - becomes
# a harmless no-op once scarlet-agents itself is republished with this
# change, at which point this COPY (and the duplicate file) can be
# removed.
COPY local_data.py /app/scarlet_agentic_harness/skills/local_data.py
