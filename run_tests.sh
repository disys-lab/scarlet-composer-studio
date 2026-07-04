#!/usr/bin/env bash
# Run the full Scarlet Composer test suite locally.
#
# Usage:
#   ./run_tests.sh              — run everything
#   ./run_tests.sh -k e2e       — run only e2e tests
#   ./run_tests.sh --no-header  — pass any extra pytest flags
#
# Prerequisites:
#   - Docker (with Compose V2)
#   - pip install -e .  (or the package already installed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE="docker compose -f docker-compose.test.yml"

cleanup() {
    echo ""
    echo "==> Stopping test services..."
    $COMPOSE down --remove-orphans
}
trap cleanup EXIT

echo "==> Building and starting test services..."
$COMPOSE up -d --build

echo "==> Waiting for Redis..."
for i in $(seq 1 30); do
    if $COMPOSE exec -T redis redis-cli -a testpassword ping 2>/dev/null | grep -q PONG; then
        echo "    Redis is up."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Redis did not become healthy in time." >&2
        exit 1
    fi
    sleep 1
done

echo "==> Waiting for mock Nebula Manager..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/health >/dev/null 2>&1; then
        echo "    Mock manager is up."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "ERROR: Mock manager did not become healthy in time." >&2
        exit 1
    fi
    sleep 1
done

echo ""
echo "==> Running tests..."
echo ""

REDIS_HOST=localhost \
REDIS_PORT=6379 \
REDIS_AUTH_TOKEN=testpassword \
MANAGER_CONTAINER_HOST=localhost \
MANAGER_CONTAINER_PORT=8080 \
MANAGER_CONTAINER_AUTH_TOKEN=dGVzdDp0ZXN0 \
python -m pytest tests/ -v --tb=short "$@"
