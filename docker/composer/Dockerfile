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

RUN if [ "$LOCAL" = "true" ]; then \
        pip install --no-cache-dir \
            /tmp/dist/scarlets-${VERSION}-*.whl \
            /tmp/dist/scarletcomposer-${VERSION}-*.whl && \
        echo "Installed scarlets + scarletcomposer ${VERSION} from local wheels"; \
    else \
        echo "LOCAL build not requested — install from Gemfury in production CI"; \
        pip install --no-cache-dir redis numpy requests click streamlit tornado GitPython python-dotenv PyYAML docker; \
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
