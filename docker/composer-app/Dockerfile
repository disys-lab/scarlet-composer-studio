# scarlet-composer app image: composer-api (FastAPI) + composer-ui (Next.js),
# combined into one container the same way Gustavo's own root Dockerfile
# combines gustavo-api + gustavo-ui - a single supervisord process manager,
# only the Next.js port exposed externally, FastAPI bound to 127.0.0.1 only.
#
# Consumes pre-built scarlets/scarletcomposer wheels from dist/ (built once
# by CI's build-wheels job from THIS commit's own source - see
# .github/workflows/multi-build.yml) rather than building them inline in
# this image's own build step. This used to build both wheels itself
# directly from source (needing .git present in the build context for
# setuptools-scm) - moved out so scarlets/scarletcomposer are built exactly
# once per CI run and shared with docker/agent-base and harness/Dockerfile,
# instead of three images each independently re-deriving the same wheel.
# Build context must be the monorepo root (needs sibling access to
# composer-api/, composer-ui/, and dist/).
FROM ubuntu:24.04

ARG py_version=python3.11
ARG node_version=20
# Baked into the composer-ui client bundle at build time (Next.js requirement
# for NEXT_PUBLIC_* vars - unlike the runtime AUTH_ENABLED the container also
# gets, this one has to be known before `npm run build` runs). Mirrors
# Gustavo's own root Dockerfile's NEXT_PUBLIC_AUTH_ENABLED handling exactly -
# without it, lib/api/client.ts's 401 -> /login redirect never fires, since
# process.env.NEXT_PUBLIC_AUTH_ENABLED is undefined in the browser bundle.
ARG NEXT_PUBLIC_AUTH_ENABLED=false

LABEL maintainer="paritosh.ramanan@okstate.edu"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ── Python base ────────────────────────────────────────────────────────────
# git dropped from this list - it was only ever needed for setuptools-scm's
# git-describe during the inline wheel build this Dockerfile no longer does.
RUN apt-get -y update && apt-get -y upgrade && \
    apt-get -y install build-essential supervisor software-properties-common curl && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get -y update && \
    apt-get -y install python3-pip ${py_version} ${py_version}-venv ${py_version}-dev && \
    apt-get purge -y build-essential && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# ── Node.js ──────────────────────────────────────────────────────────────────
RUN curl -fsSL https://deb.nodesource.com/setup_${node_version}.x | bash - && \
    apt-get -y install nodejs && \
    rm -rf /var/lib/apt/lists/*

RUN ${py_version} -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# ── Install pre-built scarlets + scarletcomposer wheels ─────────────────────
# Built once by CI's build-wheels job (see .github/workflows/multi-build.yml)
# from this exact commit, shared with docker/agent-base and harness/Dockerfile
# - not re-derived here.
COPY dist/scarlets-*.whl dist/scarletcomposer-*.whl /tmp/dist/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir /tmp/dist/scarlets-*.whl /tmp/dist/scarletcomposer-*.whl && \
    rm -rf /tmp/dist

# ── composer-api ──────────────────────────────────────────────────────────────
COPY composer-api/ /app/composer-api/
RUN pip install --no-cache-dir -r composer-api/requirements.txt

# ── composer-ui (Next.js) build ──────────────────────────────────────────────
COPY composer-ui/ /app/composer-ui/
WORKDIR /app/composer-ui
ENV NEXT_PUBLIC_AUTH_ENABLED=${NEXT_PUBLIC_AUTH_ENABLED}
RUN npm ci --prefer-offline --no-audit --no-fund && \
    npm run build && \
    cp -r .next/static .next/standalone/.next/static && \
    cp -r public .next/standalone/public 2>/dev/null || true; \
    rm -rf node_modules && \
    npm cache clean --force

# ── Runtime configuration ────────────────────────────────────────────────────
WORKDIR /app

COPY docker/composer-app/supervisord.conf /etc/supervisord.conf
COPY docker/composer-app/entrypoint.sh /usr/local/bin/composer-next
RUN chmod +x /usr/local/bin/composer-next

RUN mkdir -p /etc/scarlet-composer

# Only port 3000 (Next.js) is the public interface.
# FastAPI (:8000) binds to 127.0.0.1 only - not reachable from outside the container.
EXPOSE 3000

CMD ["composer-next", "-p", "3000"]
