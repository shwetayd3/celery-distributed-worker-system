#!/usr/bin/env bash
# Usage: bash scripts/start_worker.sh [queue_name] [concurrency]

# Examples:
#   bash scripts/start_worker.sh default 4
#   bash scripts/start_worker.sh high_priority 2
#   bash scripts/start_worker.sh io_tasks 8

set -euo pipefail

QUEUE=${1:-default}
CONCURRENCY=${2:-${WORKER_CONCURRENCY:-4}}
LOG_LEVEL=${LOG_LEVEL:-INFO}
APP_MODULE="app.celery_app:celery"

echo "=========================================="
echo "  Starting Celery Worker"
echo "  Queue       : $QUEUE"
echo "  Concurrency : $CONCURRENCY"
echo "  Log Level   : $LOG_LEVEL"
echo "=========================================="

exec celery \
  --app="$APP_MODULE" \
  worker \
  --queues="$QUEUE" \
  --concurrency="$CONCURRENCY" \
  --loglevel="$LOG_LEVEL" \
  --hostname="worker-${QUEUE}@%h" \
  --max-tasks-per-child=200 \
  --without-gossip \
  --without-mingle
