# syntax=docker/dockerfile:1
#
# scarlet-composer
#
# Operator UI for Scarlet deployments. Runs the Streamlit dashboard (port 8501)
# and the Tornado background server for node identity resolution (port 9099).
#
# Build from local wheels (development / CI — build context must be repo root):
#   docker build \
#     --build-arg VERSION=0.5.0 \
#     --build-arg LOCAL=true \
#     -t ghcr.io/disys-lab/scarlet-composer:0.5.0 \
#     -f docker/composer/Dockerfile .
#
# Build from Gemfury (production — build context must be repo root):
#   docker build \
#     --secret id=gemfury_token,env=GEMFURY_TOKEN \
#     --build-arg VERSION=0.5.0 \
#     -t ghcr.io/disys-lab/scarlet-composer:0.5.0 \
#     -f docker/composer/Dockerfile .
#
# Run:
#   docker run -p 8501:8501 -p 9099:9099 \
#     -e REDIS_HOST=redis.internal \
#     -e REDIS_AUTH_TOKEN=... \
#     ghcr.io/disys-lab/scarlet-composer:0.5.0

FROM python:3.11-slim

ARG VERSION=0.5.0
ARG LOCAL=false

LABEL org.opencontainers.image.title="scarlet-composer"
LABEL org.opencontainers.image.description="Scarlet Composer Studio — operator UI and deployment tooling"
LABEL org.opencontainers.image.version=${VERSION}
LABEL org.opencontainers.image.source="https://github.com/disys-lab/scarlet-composer-studio"
LABEL maintainer="paritosh.ramanan@okstate.edu"

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy local wheels (only used when LOCAL=true)
COPY dist/ /tmp/dist/

# LOCAL=false branch previously never actually installed scarlets/
# scarletcomposer - see docker/agent-base/Dockerfile's identical fix for
# the full explanation. Wires the --secret id=gemfury_token,env=GEMFURY_TOKEN
# mechanism this file's own build example above already documented.
RUN --mount=type=secret,id=gemfury_token \
    if [ "$LOCAL" = "true" ]; then \
        pip install --no-cache-dir \
            /tmp/dist/scarlets-${VERSION}-*.whl \
            /tmp/dist/scarletcomposer-${VERSION}-*.whl && \
        echo "Installed scarlets + scarletcomposer ${VERSION} from local wheels"; \
    else \
        GEMFURY_TOKEN="$(cat /run/secrets/gemfury_token 2>/dev/null || true)"; \
        if [ -z "$GEMFURY_TOKEN" ]; then \
            echo "ERROR: LOCAL=false (the default) requires --secret id=gemfury_token,env=GEMFURY_TOKEN - see this file's own build examples above, or pass --build-arg LOCAL=true with local wheels in dist/ instead." >&2; \
            exit 1; \
        fi; \
        pip install --no-cache-dir --extra-index-url "https://${GEMFURY_TOKEN}@pypi.fury.io/osu-home-stri/" \
            "scarlets==${VERSION}" "scarletcomposer==${VERSION}" && \
        echo "Installed scarlets + scarletcomposer ${VERSION} from Gemfury"; \
    fi && \
    rm -rf /tmp/dist

# Runtime environment variables
ENV REDIS_HOST="" \
    REDIS_PORT="6379" \
    REDIS_AUTH_TOKEN="" \
    MANAGER_HOST="" \
    MANAGER_PORT="8080"

EXPOSE 8501 9099

CMD ["scarlet-composer", "composer", "gui"]
