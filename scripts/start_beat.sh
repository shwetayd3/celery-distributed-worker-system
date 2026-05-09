#!/usr/bin/env bash

# Starts the Celery Beat scheduler.

# NOTE : Run exactly ONE instance of Beat at a time.
# Multiple Beat instances will double-schedule every task.

# Usage:
#   bash scripts/start_beat.sh
#   LOG_LEVEL=DEBUG bash scripts/start_beat.sh
