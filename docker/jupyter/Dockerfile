# scarlet-notebooks — extends scarlet-agent-base
#
# JupyterLab image preloaded with runnable tutorials for the scarlets SDK
# (Messenger, Mapper, Federator), the data-sources registry, and the LLM
# agent fleet walkthrough (notebook 06). Not a deployable agent - a
# teaching/exploration environment, same "extend scarlet-agent-base, run
# one process under supervisord-less CMD" shape as
# examples/quickstart/hello_agent/Dockerfile and harness/Dockerfile.
#
# Notebook 06 launches a real agent fleet, but this image is only ever a
# *client* of that fleet - it talks to the head's MCP server and reads the
# Scarlets registry over Redis. It deliberately does NOT extend
# scarlet-agents: nothing here imports scarlet_agentic_harness, and the
# one dependency that ever justified doing so (`mcp`) is a plain pip
# package, now pinned in docker/jupyter/requirements.txt. One image
# therefore serves all six notebooks.
#
# Build (context must be the repo root - this Dockerfile only needs its own
# sibling notebooks/ directory, but follows the same repo-root-context
# convention as docker/agent-base and docker/composer-app for consistency
# with CI):
#   docker build \
#     --build-arg BASE_VERSION=0.5.0 \
#     -f docker/jupyter/Dockerfile \
#     -t scarlet-notebooks:latest .
#
# Run standalone (for local testing without compose - see
# examples/notebooks/docker-compose.yml for the documented way to run this
# against a real Redis instance):
#   docker run --rm -p 8888:8888 \
#     -e REDIS_HOST=... -e REDIS_AUTH_TOKEN=... \
#     scarlet-notebooks:latest

ARG BASE_VERSION=0.5.0
FROM ghcr.io/disys-lab/scarlet-agent-base:${BASE_VERSION}

LABEL org.opencontainers.image.title="scarlet-notebooks"
LABEL org.opencontainers.image.description="JupyterLab tutorials for the scarlets SDK (Messenger, Mapper, Federator, data sources, LLM agent fleets)"
LABEL org.opencontainers.image.source="https://github.com/disys-lab/scarlet-composer-studio"

# Docker CLI + compose plugin. Notebook 06 brings the tutorial agent fleet
# up by shelling out to `docker compose --profile agents up -d` against the
# compose file bind-mounted in at /workspace (see
# examples/notebooks/docker-compose.yml), driving the host's Docker daemon
# through the socket that same compose file mounts in. Only the CLI is
# needed for that - no dockerd, and no `docker` Python SDK either (nothing
# in this image imports it).
#
# Installed from Docker's own apt repo rather than Debian's, which ships
# neither a current CLI nor the compose v2 plugin at all. The base is
# python:3.11-slim (Debian 13 trixie) by way of scarlet-agent-base - same
# distro harness/Dockerfile's own msodbcsql18 install targets, so the
# keyring-not-apt-key convention there applies here too (trixie has
# dropped apt-key entirely).
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get -y update && \
    apt-get -y install --no-install-recommends ca-certificates curl gnupg && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg \
        -o /etc/apt/keyrings/docker.asc && \
    chmod a+r /etc/apt/keyrings/docker.asc && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list && \
    apt-get -y update && \
    apt-get -y install --no-install-recommends docker-ce-cli docker-compose-plugin && \
    apt-get -y purge gnupg && apt-get -y autoremove && \
    rm -rf /var/lib/apt/lists/*

# Every pip package this image needs beyond scarlet-agent-base, pinned to
# exact versions - see docker/jupyter/requirements.txt's own header for
# what each one is for and why it's pinned rather than floored.
COPY docker/jupyter/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

WORKDIR /notebooks
COPY docker/jupyter/notebooks/ /notebooks/

EXPOSE 8888

# --NotebookApp.token="" - this image is meant to run behind the same
# private/local network as the rest of a Scarlet deployment (matching
# hello_agent/harness's own no-auth-in-image posture); put a reverse proxy
# with real auth in front of it for anything more exposed than that.
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=", "--NotebookApp.notebook_dir=/notebooks"]
