"""
Two production-grade periodic tasks run by Celery Beat:
 
  1. system_health_check  — runs every 60s
     Checks Redis connectivity, worker availability, and queue depths.
     Logs a structured health report and raises an alert if anything looks wrong.
 
  2. stale_result_cleanup — runs every hour
     Scans Redis for Celery result keys older than the configured TTL and
     deletes them, preventing unbounded memory growth when result_expires
     alone is not enough (e.g. tasks that never polled their result).
"""

import time
import logging
from datetime import datetime, timezone

import redis as redis_lib
 
from app.celery_app import celery
from config.app_config import Config
 
logger = logging.getLogger(__name__)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Task 1 — System Health Check  (every 60 seconds)
# ─────────────────────────────────────────────────────────────────────────────
 
@celery.task(
    bind=True,
    name="periodic.system_health_check",
    max_retries=0,          # never retry a health check — just run again next tick
    queue="default",
    ignore_result=False,
)
def system_health_check(self) -> dict:
    """
    Runs every 60 seconds via Celery Beat.
 
    Checks:
      - Redis ping (broker reachability)
      - Active worker count across all queues
      - Per-queue depth (reserved + active tasks)
      - Overall system status: OK | DEGRADED | DOWN
 
    Returns a structured health report dict persisted to the result backend
    so the Flask /health endpoint can surface it without hitting Redis directly.
    """
    report = {
        "task_id": self.request.id,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "redis": {},
        "workers": {},
        "queues": {},
        "status": "OK",
        "warnings": [],
    }
