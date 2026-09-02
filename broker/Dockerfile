# Data-source broker - one instance per data source, deployed co-located
# with it (a plain Gustavo app - see main.py's own docstring for the full
# architecture). This is intentionally its own small image, separate from
# scarlet-composer-app: it needs its own Dockerfile/lifecycle (a different
# connector type means different system dependencies entirely - MS SQL's
# ODBC/Kerberos stack below has nothing to do with, say, a future PI
# connector), and bundling it into the main app image would force
# composer-api/composer-ui onto whatever network_mode this broker needs
# (network_mode: host, for the same real, empirically-verified reason
# docker/composer-app/background_server.py needs it - see that file).
FROM ubuntu:24.04

ARG py_version=python3.11

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# System dependencies for the mssql connector's Windows/AD Integrated auth -
# mirrors assurant_decentralized_analytics/claim_analytics/Dockerfile's own
# already-proven install exactly (msodbcsql18 + krb5-user/keyutils for a
# real Kerberos ticket + unixodbc for pyodbc itself), not rediscovered.
# A future connector type that doesn't need Kerberos/ODBC at all would not
# need any of this - it's specific to this one connector, not a broker-wide
# requirement.
RUN apt-get -y update && apt-get -y upgrade && \
    apt-get -y install build-essential curl gnupg2 apt-transport-https \
        ca-certificates krb5-user keyutils unixodbc unixodbc-dev \
        software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get -y update && \
    apt-get -y install python3-pip ${py_version} ${py_version}-venv ${py_version}-dev && \
    apt-get purge -y build-essential && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/ubuntu/22.04/prod.list > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && ACCEPT_EULA=Y apt-get install -y msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

RUN ${py_version} -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Kerberos keytab + krb5.conf are mounted in at deploy time (matching how
# `config` volumes already work elsewhere in this platform) and kinit'd
# here, before uvicorn starts - the mssql connector assumes a valid ticket
# already exists by the time query() is ever called. KEYTAB_PATH/
# KRB5_PRINCIPAL are set per-deployment; this entrypoint is a no-op (skips
# kinit) if they're unset, so a future non-Kerberos connector isn't forced
# through this step.
COPY entrypoint.sh /usr/local/bin/broker-entrypoint
RUN chmod +x /usr/local/bin/broker-entrypoint

EXPOSE 8090

CMD ["/usr/local/bin/broker-entrypoint"]
