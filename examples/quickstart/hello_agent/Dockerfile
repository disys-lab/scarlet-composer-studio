# hello-agent — extends scarlet-agent-base
#
# Build:
#   docker build -t hello-agent:latest .
#
# Run standalone (for local testing without compose):
#   docker run --rm \
#     -e REDIS_HOST=... -e REDIS_AUTH_TOKEN=... \
#     -e APP_ID=hello-agent -e NODE_ADDRESS=local \
#     hello-agent:latest

ARG BASE_VERSION=0.5.0
FROM ghcr.io/disys-lab/scarlet-agent-base:${BASE_VERSION}

WORKDIR /app

COPY hello_agent.py /app/hello_agent.py
COPY supervisord.conf /etc/supervisor/conf.d/hello_agent.conf

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/hello_agent.conf"]
