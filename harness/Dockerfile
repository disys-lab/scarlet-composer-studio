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
# Build:
#   docker build \
#     --build-arg BASE_VERSION=0.5.0 \
#     -t scarlet-agents:latest .
#
# Run standalone (for local testing without compose - see docker-compose.yml
# for running this alongside scarlet-composer's operator UI):
#   docker run --rm \
#     -e REDIS_HOST=... -e REDIS_AUTH_TOKEN=... \
#     -e ROLE=worker -e APP_ID=scarlet-agents -e NODE_ADDRESS=local \
#     -e LLM_BASE_URL=... -e LLM_API_KEY=... -e LLM_MODEL=... \
#     scarlet-agents:latest

ARG BASE_VERSION=0.5.0
FROM ghcr.io/disys-lab/scarlet-agent-base:${BASE_VERSION}

WORKDIR /app

# scarlet-agent-base already provides the scarlets API (redis/numpy/requests
# or the real scarlets wheel, per its own LOCAL build-arg) - openai and mcp
# are the extra runtime dependencies this harness adds on top
# (scarlet_agentic_harness/llm/client.py, mcp_server.py).
RUN pip install --no-cache-dir openai>=1.0.0 mcp>=2.0.0

# Only what's needed to install and run the package - tests/, transcripts/,
# and dev tooling are excluded via .dockerignore, keeping this a runtime
# image, not a dev checkout.
COPY setup.py README.md /app/
COPY scarlet_agentic_harness/ /app/scarlet_agentic_harness/

# --no-deps: scarlet-agent-base already provides `scarlets` (installed from
# Gemfury or a local wheel, per its own build-arg) - letting pip re-resolve
# setup.py's `scarlets @ git+https://...` requirement here would silently
# reinstall a different (git HEAD) version on top of whatever the base image
# intentionally pinned. openai is already installed explicitly above.
RUN pip install --no-cache-dir --no-deps .

COPY supervisord.conf /etc/supervisor/conf.d/scarlet_agents.conf

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
