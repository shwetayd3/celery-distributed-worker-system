#!/usr/bin/env bash

# Starts the Celery Beat scheduler.

# NOTE : Run exactly ONE instance of Beat at a time.
# Multiple Beat instances will double-schedule every task.

# Usage:
#   bash scripts/start_beat.sh
#   LOG_LEVEL=DEBUG bash scripts/start_beat.sh

set -euo pipefail
 
APP_MODULE="app.celery_app:celery"
LOG_LEVEL=${LOG_LEVEL:-INFO}
SCHEDULE_FILE=${BEAT_SCHEDULE_FILE:-/var/run/celery/celerybeat-schedule}
PIDFILE=${BEAT_PIDFILE:-/var/run/celery/celerybeat.pid}
 
# Ensure the directory for the schedule db and pidfile exists
mkdir -p "$(dirname "$SCHEDULE_FILE")"
 
echo "=========================================="
echo "  Starting Celery Beat Scheduler"
echo "  App         : $APP_MODULE"
echo "  Schedule DB : $SCHEDULE_FILE"
echo "  PID file    : $PIDFILE"
echo "  Log Level   : $LOG_LEVEL"
echo "=========================================="
echo "  WARNING: Only run ONE Beat instance!"
echo "=========================================="
 
exec celery \
  --app="$APP_MODULE" \
  beat \
  --loglevel="$LOG_LEVEL" \
  --schedule="$SCHEDULE_FILE" \
  --pidfile="$PIDFILE" \
  --max-interval=5
