# Data-source broker - one instance per data source, deployed co-located
# with it (a plain Gustavo app - see main.py's own docstring for the full
# architecture). This is intentionally its own small image, separate from
# scarlet-composer-app: it needs its own Dockerfile/lifecycle, and bundling
# it into the main app image would force composer-api/composer-ui onto
# whatever network_mode this broker needs (network_mode: host, for the
# same real, empirically-verified reason docker/composer-app/
# background_server.py needs it - see that file).
#
# Build context is the REPO ROOT, not broker/ itself:
#   docker build -f broker/Dockerfile .
# broker/ depends on the sibling data_connectors/ package (the six
# connector classes), which needs to be reachable from the build context -
# see the data_connectors install step below.
FROM ubuntu:24.04

ARG py_version=python3.11

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System dependencies for both connector types' Kerberos needs - mssql's
# Windows/AD Integrated auth (mirrors assurant_decentralized_analytics/
# claim_analytics/Dockerfile's own already-proven install: msodbcsql18 +
# krb5-user/keyutils for a real ticket + unixodbc for pyodbc itself) and
# pi's gssapi build (libkrb5-dev - mirrors PITalk/Dockerfile's own install,
# needed even where a deployment only ever uses PI's basic-auth security
# method, since PIServer.py imports HTTPKerberosAuth unconditionally).
# build-essential/*-dev headers are kept until after both pip install
# steps below (not purged in this same layer) since gssapi may need to
# compile from source if no prebuilt wheel matches this exact
# Ubuntu/Python combination.
RUN apt-get -y update && apt-get -y upgrade && \
    apt-get -y install build-essential curl gnupg2 apt-transport-https \
        ca-certificates krb5-user keyutils libkrb5-dev unixodbc unixodbc-dev \
        software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get -y update && \
    apt-get -y install python3-pip ${py_version} ${py_version}-venv ${py_version}-dev && \
    rm -rf /var/lib/apt/lists/*

RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

RUN ${py_version} -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY broker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# data_connectors (../data_connectors, setup_connectors.py) - the six
# connector classes, built from this same repo checkout. Non-standard
# setup filename (mirrors scarletcomposer's own setup_composer.py in this
# repo), so pip can't resolve it as a plain requirements.txt line - build
# a wheel and install that, same discipline used elsewhere in this
# project to avoid stale .eggs/build-cache issues with `setup.py develop`.
COPY data_connectors/ /tmp/data_connectors/data_connectors/
COPY setup_connectors.py /tmp/data_connectors/setup_connectors.py
RUN pip install --no-cache-dir setuptools wheel setuptools-scm && \
    cd /tmp/data_connectors && python setup_connectors.py bdist_wheel && \
    pip install --no-cache-dir dist/*.whl && \
    cd / && rm -rf /tmp/data_connectors

# The real pitalk package (github.com/blockalytics/PITalk), --no-deps -
# see requirements.txt's own comment for why its setup.py's own pins
# aren't used instead (no installable wheel for a modern Python).
RUN pip install --no-cache-dir --no-deps "git+https://github.com/blockalytics/PITalk.git"

RUN apt-get -y purge build-essential && \
    apt-get -y autoremove && \
    rm -rf /var/lib/apt/lists/*

COPY broker/ .

# Kerberos keytab + krb5.conf are mounted in at deploy time (matching how
# `config` volumes already work elsewhere in this platform) and kinit'd
# here, before uvicorn starts - the mssql connector assumes a valid ticket
# already exists by the time query() is ever called. KEYTAB_PATH/
# KRB5_PRINCIPAL are set per-deployment; this entrypoint is a no-op (skips
# kinit) if they're unset, so a future non-Kerberos connector isn't forced
# through this step.
COPY broker/entrypoint.sh /usr/local/bin/broker-entrypoint
RUN chmod +x /usr/local/bin/broker-entrypoint

EXPOSE 8090

CMD ["/usr/local/bin/broker-entrypoint"]
