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

RUN if [ "$LOCAL" = "true" ]; then \
        pip install --no-cache-dir /tmp/dist/scarlets-${VERSION}-*.whl && \
        echo "Installed scarlets ${VERSION} from local wheel"; \
    else \
        echo "LOCAL build not requested — install scarlets from Gemfury in production CI"; \
        pip install --no-cache-dir redis numpy requests; \
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
