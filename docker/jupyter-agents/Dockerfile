# scarlet-notebooks-agents — extends scarlet-agents (not scarlet-agent-base)
#
# JupyterLab image for the one notebook that needs more than the plain
# scarlets SDK: the harness package, an LLM client, and MCP - all already
# baked into scarlet-agents (harness/Dockerfile), so this adds nothing new
# on that front. What it does add on top, beyond jupyterlab/pandas/
# matplotlib (same three as docker/jupyter/Dockerfile): the `docker` SDK
# and a Docker socket mount at run time, so the notebook itself can launch
# and tear down real scarlet-agents head/worker containers - see
# examples/notebook-agents/README.md for why this lives in its own image
# rather than extending docker/jupyter/Dockerfile's existing one: giving
# the plain SDK-tutorial notebooks control over the Docker host would be
# a real, unwarranted increase in what that container can do, for a
# capability only this one notebook needs.
#
# Build (context must be the repo root, same convention as every other
# image here):
#   docker build \
#     --build-arg AGENTS_VERSION=0.5.0 \
#     -f docker/jupyter-agents/Dockerfile \
#     -t scarlet-notebooks-agents:latest .
#
# Run standalone (for local testing without compose - see
# examples/notebook-agents/docker-compose.yml for the documented way to
# run this, including the Docker socket mount and the host-path env var
# the notebook needs to bind-mount CSVs into sibling containers it
# launches):
#   docker run --rm -p 8888:8888 \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     -e REDIS_HOST=... -e REDIS_AUTH_TOKEN=... \
#     scarlet-notebooks-agents:latest

ARG AGENTS_VERSION=0.5.0
FROM ghcr.io/disys-lab/scarlet-agents:${AGENTS_VERSION}

LABEL org.opencontainers.image.title="scarlet-notebooks-agents"
LABEL org.opencontainers.image.description="JupyterLab tutorial that launches and talks to real scarlet-agents head/worker containers over MCP"
LABEL org.opencontainers.image.source="https://github.com/disys-lab/scarlet-composer-studio"

# jupyterlab/pandas/matplotlib: same as docker/jupyter/Dockerfile.
# docker: the one genuinely new dependency this notebook needs - talks to
# the Docker socket mounted in at run time to launch/stop sibling
# containers. Everything else (scarlets, the harness package, openai,
# mcp, data_connectors) is already present in the scarlet-agents base.
RUN pip install --no-cache-dir jupyterlab pandas matplotlib docker

WORKDIR /notebooks
COPY docker/jupyter-agents/notebooks/ /notebooks/

# The tutorial worker image's own build context - notebook 06 builds an
# image from this at runtime, via the Docker SDK, before launching worker
# containers from it. See docker/jupyter-agents/worker-image/Dockerfile's
# own comment for why this is a separate image rather than something
# baked into scarlet-agents itself.
COPY docker/jupyter-agents/worker-image/ /worker-image/

EXPOSE 8888

# Overrides scarlet-agents' own default CMD (supervisord -> the harness's
# __main__.py) entirely - this container is a Jupyter environment, not a
# running head/worker itself. See the Dockerfile-level comment above for
# why supervisord.conf is never touched or invoked here, deliberately.
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=", "--NotebookApp.notebook_dir=/notebooks"]
