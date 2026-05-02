#!/usr/bin/env bash
# Usage: bash scripts/start_flower.sh
# Starts the Flower monitoring dashboard on port 5555

set -euo pipefail

APP_MODULE="app.celery_app:celery"
FLOWER_PORT=${FLOWER_PORT:-5555}
FLOWER_BASIC_AUTH=${FLOWER_BASIC_AUTH:-"admin:secret"}

echo "=========================================="
echo "  Starting Flower Dashboard"
echo "  URL  : http://0.0.0.0:${FLOWER_PORT}"
echo "  Auth : ${FLOWER_BASIC_AUTH%%:*}:***"
echo "=========================================="

exec celery \
  --app="$APP_MODULE" \
  flower \
  --conf=monitoring/flower_config.py \
  --port="$FLOWER_PORT" \
  --basic-auth="$FLOWER_BASIC_AUTH" \
  --loglevel=INFO
