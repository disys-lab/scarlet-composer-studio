# syntax=docker/dockerfile:1
#
# scarlet-agent-base
#
# Base image for Scarlet agent containers. Provides the scarlets API
# (Mapper, Messenger, Federator) and supervisor.
#
# Build from local wheel (development / CI — build context must be repo root):
#   docker build \
#     --build-arg VERSION=0.5.0 \
#     --build-arg LOCAL=true \
#     -t ghcr.io/disys-lab/scarlet-agent-base:0.5.0 \
#     -f docker/agent-base/Dockerfile .
#
# Build from Gemfury (production — build context must be repo root):
#   docker build \
#     --secret id=gemfury_token,env=GEMFURY_TOKEN \
#     --build-arg VERSION=0.5.0 \
#     -t ghcr.io/disys-lab/scarlet-agent-base:0.5.0 \
#     -f docker/agent-base/Dockerfile .
#
# Extend:
#   FROM ghcr.io/disys-lab/scarlet-agent-base:0.5.0
#   COPY my_agent.py /app/
#   CMD ["python3", "/app/my_agent.py"]

FROM python:3.11-slim

ARG VERSION=0.5.0
ARG LOCAL=false

LABEL org.opencontainers.image.title="scarlet-agent-base"
LABEL org.opencontainers.image.description="Base image for Scarlet agent containers — scarlets API + supervisor"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.source="https://github.com/disys-lab/scarlet-composer-studio"
LABEL maintainer="paritosh.ramanan@okstate.edu"

RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Copy local wheel (only used when LOCAL=true; file is excluded by .dockerignore in production)
COPY dist/ /tmp/dist/

# LOCAL=false branch previously never actually installed scarlets - it only
# echoed that it did, then installed scarlets' own transitive deps
# (redis/numpy/requests) directly, leaving `import scarlets` broken in any
# image built the documented "production" way (no --build-arg LOCAL=true).
# Fixed to actually use the --secret id=gemfury_token,env=GEMFURY_TOKEN
# mechanism this file's own build example above already documented but
# never wired in. `pip install scarlets==${VERSION}` resolves its
# dependencies itself (declared in scarlets' own setup.py) - no need to
# list redis/numpy/requests separately once the real package is installed.
RUN --mount=type=secret,id=gemfury_token \
    if [ "$LOCAL" = "true" ]; then \
        pip install --no-cache-dir /tmp/dist/scarlets-${VERSION}-*.whl && \
        echo "Installed scarlets ${VERSION} from local wheel"; \
    else \
        GEMFURY_TOKEN="$(cat /run/secrets/gemfury_token 2>/dev/null || true)"; \
        if [ -z "$GEMFURY_TOKEN" ]; then \
            echo "ERROR: LOCAL=false (the default) requires --secret id=gemfury_token,env=GEMFURY_TOKEN - see this file's own build examples above, or pass --build-arg LOCAL=true with a local wheel in dist/ instead." >&2; \
            exit 1; \
        fi; \
        pip install --no-cache-dir --extra-index-url "https://${GEMFURY_TOKEN}@pypi.fury.io/osu-home-stri/" "scarlets==${VERSION}" && \
        echo "Installed scarlets ${VERSION} from Gemfury"; \
    fi && \
    rm -rf /tmp/dist

# Runtime environment variables — all overridable at deploy time via Gustavo or docker-compose
ENV REDIS_HOST="" \
    REDIS_PORT="6379" \
    REDIS_AUTH_TOKEN="" \
    APP_ID="" \
    NODE_ADDRESS="" \
    DEVICE_GROUP="" \
    MANAGER_HOST="" \
    MANAGER_PORT="8080" \
    LLM_BASE_URL="" \
    LLM_API_KEY="" \
    MODEL_NAME=""

WORKDIR /app
