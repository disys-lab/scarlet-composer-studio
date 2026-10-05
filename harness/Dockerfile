# syntax=docker/dockerfile:1
#
# scarlet-agents — extends scarlet-agent-base
#
# Runs scarlet_agentic_harness as a supervised process (ROLE=head or
# ROLE=worker, same image either way - see README.md and __main__.py).
# Follows the same pattern as scarlet-composer-studio's own hello_agent
# quickstart example: extend scarlet-agent-base, copy the agent in, run it
# under supervisord for autorestart. Not deployed anywhere yet - see
# README.md's Status section.
#
# Build (context must be the monorepo root, not harness/ itself - this
# Dockerfile needs sibling access to dist/ for the pre-built data_connectors
# wheel, same convention docker/agent-base and docker/composer-app use):
#   docker build \
#     --build-arg BASE_VERSION=0.5.0 \
#     -f harness/Dockerfile \
#     -t scarlet-agents:latest .
#
# Run standalone (for local testing without compose - see docker-compose.yml
# for running this alongside scarlet-composer's operator UI):
#   docker run --rm \
#     -e REDIS_HOST=... -e REDIS_AUTH_TOKEN=... \
#     -e ROLE=worker -e APP_ID=scarlet-agents -e NODE_ADDRESS=local \
#     -e LLM_BASE_URL=... -e LLM_API_KEY=... -e LLM_MODEL=... \
#     scarlet-agents:latest

# Keep this in step with the current scarlet-agent-base release. CI passes
# BASE_VERSION explicitly, so this default only governs local builds - which
# is exactly why it is worth getting right: a stale default is invisible.
#
# It was left at 0.5.0 while the published agents moved to 0.5.6, and the
# two differ in how scarlets' Messenger stores an inbox:
#
#   0.5.0   r.set(key, ...)           one string key per message
#   0.5.6   r.hset(inbox, seq, ...)   one hash per agent
#
# composer-api reads inboxes with hgetall, so against a 0.5.0-built agent
# every read raises WRONGTYPE, gets swallowed by its per-inbox try/except,
# and the Conversations view silently shows nothing at all. Nothing errors,
# nothing logs at the UI, and the agents themselves work perfectly - which
# makes it a genuinely expensive hour to diagnose.
#
# Pinned rather than `latest` so a local build stays reproducible (as of
# writing they resolve to the same digest). Bump it when a new base ships.
ARG BASE_VERSION=0.5.6
FROM ghcr.io/disys-lab/scarlet-agent-base:${BASE_VERSION}

WORKDIR /app

# System dependencies for pyodbc (mssql) and requests-kerberos/pi's gssapi
# build - mirrors broker/Dockerfile's own already-proven install
# (msodbcsql18 + krb5-user/keyutils/libkrb5-dev + unixodbc), adapted for
# this image's actual base (python:3.11-slim / Debian, not broker's
# ubuntu:24.04): no software-properties-common/deadsnakes ppa needed here,
# Python 3.11 is already scarlet-agent-base's own system Python.
# build-essential is purged after all pip installs below (pyodbc/gssapi
# may need to compile from source if no prebuilt wheel matches this exact
# Debian/Python combination), same discipline as broker/Dockerfile.
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get -y update && apt-get -y upgrade && \
    apt-get -y install --no-install-recommends build-essential curl \
        ca-certificates krb5-user keyutils libkrb5-dev unixodbc unixodbc-dev && \
    rm -rf /var/lib/apt/lists/*

# msodbcsql18 - Microsoft's own repo, not Debian's. broker/Dockerfile
# fetches keys/microsoft.asc directly and `apt-key add`s it (fine on its
# ubuntu:24.04 base) - verified directly (this session) that this doesn't
# work here: this base's Debian 13 (trixie) has dropped apt-key entirely,
# AND keys/microsoft.asc turns out to be the wrong key regardless - the
# trixie repo's InRelease is actually signed by a newer key
# ("Microsoft Corporation - General GPG Signer", 2023) that endpoint
# doesn't contain. Microsoft's own officially-documented bootstrap
# (packages-microsoft-prod.deb) carries the correct key and sources list
# together and is what actually works - confirmed directly against this
# exact base image.
RUN curl -sSL -O https://packages.microsoft.com/config/debian/13/packages-microsoft-prod.deb && \
    dpkg -i packages-microsoft-prod.deb && \
    rm packages-microsoft-prod.deb && \
    apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

# Every pip package this image's runtime code needs beyond what
# scarlet-agent-base already provides - centralized in
# harness/requirements-image.txt (not inline pip installs, not
# harness/setup.py's own install_requires) specifically because both the
# data_connectors wheel below and the harness package itself further down
# are installed --no-deps, so nothing pulls these in automatically. See
# that file's own header comment for why it's separate from
# harness/requirements.txt (the dev/test install file) and the full
# breakdown of what needs what.
COPY harness/requirements-image.txt /tmp/requirements-image.txt
RUN pip install --no-cache-dir -r /tmp/requirements-image.txt && \
    rm /tmp/requirements-image.txt

# data_connectors (setup_connectors.py, monorepo root) - local_config.py's
# build_connector() constructs these same connector classes in-process for
# mode: local data sources. Built once by CI's build-wheels job alongside
# scarlets/scarletcomposer (see .github/workflows/multi-build.yml) and
# handed to every image that needs it via this same dist/ artifact - not
# re-derived here. --no-deps for the same reason as the harness package
# install below: data-connectors' own dependency resolution shouldn't
# clobber what's already pinned in this image.
#
# Includes the pi connector's real `pitalk` package, vendored at
# data_connectors/pitalk/ (a byte-for-byte copy of the actual package
# source) and built into this same wheel by setup_connectors.py, rather
# than `pip install git+https://github.com/blockalytics/PITalk.git` the
# way broker/Dockerfile's identical-looking (and currently broken) line
# still does - verified directly (this session) that
# github.com/blockalytics/PITalk is actually a private repo: cloning it
# from a clean environment with no GitHub credentials cached fails
# outright. No GitHub access needed here, ever.
COPY dist/data_connectors-*.whl /tmp/dist/
RUN pip install --no-cache-dir --no-deps /tmp/dist/data_connectors-*.whl && \
    rm -rf /tmp/dist

# Only what's needed to install and run the package - tests/, transcripts/,
# and dev tooling are excluded via .dockerignore, keeping this a runtime
# image, not a dev checkout.
COPY harness/setup.py harness/README.md /app/
COPY harness/scarlet_agentic_harness/ /app/scarlet_agentic_harness/

# --no-deps: scarlet-agent-base already provides `scarlets` (installed from
# Gemfury or a local wheel, per its own build-arg), and data-connectors was
# just installed above - letting pip re-resolve setup.py's own
# install_requires here would attempt to re-derive both from PyPI/Gemfury
# and could clobber the exact wheels this build already pinned. openai/mcp
# are already installed explicitly above.
RUN pip install --no-cache-dir --no-deps .

RUN apt-get -y purge build-essential && \
    apt-get -y autoremove && \
    rm -rf /var/lib/apt/lists/*

COPY harness/supervisord.conf /etc/supervisor/conf.d/scarlet_agents.conf

# ROLE selects head vs. worker inside __main__.py - same image either way.
# HEAD_BUS/LLM_MODEL aren't declared in scarlet-agent-base's own ENV list
# (it predates this harness); MODEL_NAME there is unrelated (a different
# env var name) - set explicitly here so `docker run`/compose only need to
# override what's actually different per deployment.
#
# Defaults to worker: __main__.py's ROLE=head branch is currently an
# interactive REPL (reads sys.stdin line by line - see its own docstring,
# "for local/manual runs... while building"), not yet a headless daemon.
# Under supervisord in a detached container, stdin is closed, so ROLE=head
# would hit EOF immediately and crash-loop under autorestart. Use
# `docker run -it ... -e ROLE=head ...` (bypassing supervisord, or with
# stdin properly attached) for head/manual-dispatch use until __main__.py's
# head branch becomes a real daemon - not something to fix inside a
# Dockerfile. mcp_server.py (python -m scarlet_agentic_harness.mcp_server,
# MCP_TRANSPORT=streamable-http) is a genuine headless alternative for a
# head role - it needs no stdin at all - but isn't wired as this image's
# default CMD; run it as a separate `docker run`/supervisord program if
# you need an MCP-reachable head.
ENV ROLE="worker" \
    HEAD_BUS="" \
    LLM_MODEL=""

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/scarlet_agents.conf"]
