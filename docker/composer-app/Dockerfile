# scarlet-composer app image: composer-api (FastAPI) + composer-ui (Next.js),
# combined into one container the same way Gustavo's own root Dockerfile
# combines gustavo-api + gustavo-ui - a single supervisord process manager,
# only the Next.js port exposed externally, FastAPI bound to 127.0.0.1 only.
#
# Builds scarlets/scarletcomposer as wheels from THIS repo's own source
# (setup.py / setup_composer.py) rather than installing from Gemfury/PyPI -
# this image IS the scarlets/scarletcomposer source tree's own deployment,
# so there's no separate "published version" to pin against here the way
# docker/agent-base and docker/composer (which install scarlets as an
# external dependency) do.
FROM ubuntu:24.04

ARG py_version=python3.11
ARG node_version=20

LABEL maintainer="paritosh.ramanan@okstate.edu"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ── Python base ────────────────────────────────────────────────────────────
RUN apt-get -y update && apt-get -y upgrade && \
    apt-get -y install build-essential supervisor software-properties-common curl git && \
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
COPY . .

# ── Build scarlets + scarletcomposer wheels from this checkout, install them ──
# git history is what setuptools-scm derives a version from - .git is
# present in a real checkout/archive but excluded from a shallow context,
# so this needs the real repo, not just a tarball of the working tree.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel setuptools-scm build && \
    rm -rf build *.egg-info .eggs && \
    python setup.py bdist_wheel && \
    rm -rf build *.egg-info && \
    python setup_composer.py bdist_wheel && \
    pip install --no-cache-dir dist/scarlets-*.whl dist/scarletcomposer-*.whl

# ── composer-api requirements ────────────────────────────────────────────────
RUN pip install --no-cache-dir -r composer-api/requirements.txt

# ── composer-ui (Next.js) build ──────────────────────────────────────────────
WORKDIR /app/composer-ui
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
