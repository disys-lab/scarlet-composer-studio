# scarlet-notebooks — extends scarlet-agent-base
#
# JupyterLab image preloaded with runnable tutorials for the scarlets SDK
# (Messenger, Mapper, Federator) and the data-sources registry. Not a
# deployable agent - a teaching/exploration environment, same "extend
# scarlet-agent-base, run one process under supervisord-less CMD" shape as
# examples/quickstart/hello_agent/Dockerfile and harness/Dockerfile.
#
# Build (context must be the repo root - this Dockerfile only needs its own
# sibling notebooks/ directory, but follows the same repo-root-context
# convention as docker/agent-base and docker/composer-app for consistency
# with CI):
#   docker build \
#     --build-arg BASE_VERSION=0.5.0 \
#     -f docker/notebooks/Dockerfile \
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
LABEL org.opencontainers.image.description="JupyterLab tutorials for the scarlets SDK (Messenger, Mapper, Federator, data sources)"
LABEL org.opencontainers.image.source="https://github.com/disys-lab/scarlet-composer-studio"

# pandas/matplotlib are only needed by the notebooks themselves
# (timeseries/regression plotting) - scarlet-agent-base already provides
# scarlets' own runtime deps (redis, numpy, requests).
RUN pip install --no-cache-dir jupyterlab pandas matplotlib

WORKDIR /notebooks
COPY docker/notebooks/notebooks/ /notebooks/

EXPOSE 8888

# --NotebookApp.token="" - this image is meant to run behind the same
# private/local network as the rest of a Scarlet deployment (matching
# hello_agent/harness's own no-auth-in-image posture); put a reverse proxy
# with real auth in front of it for anything more exposed than that.
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=", "--NotebookApp.notebook_dir=/notebooks"]
