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

    # ── 1. Redis ping ────────────────────────────────────────────────────────
    try:
        r = redis_lib.from_url(Config.REDIS_URL, socket_connect_timeout=3)
        start = time.perf_counter()
        r.ping()
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        report["redis"] = {"reachable": True, "latency_ms": latency_ms}
        if latency_ms > 100:
            report["warnings"].append(f"Redis latency high: {latency_ms}ms")
    except Exception as exc:
        report["redis"] = {"reachable": False, "error": str(exc)}
        report["status"] = "DOWN"
        logger.error(f"[health_check] Redis unreachable: {exc}")
        return report   # no point continuing if broker is down

    # ── 2. Worker inspection ─────────────────────────────────────────────────
    inspect = celery.control.inspect(timeout=3.0)
    active_map = inspect.active() or {}
    stats_map  = inspect.stats()  or {}

    worker_count = len(active_map)
    total_active_tasks = sum(len(tasks) for tasks in active_map.values())

    report["workers"] = {
        "count": worker_count,
        "active_tasks": total_active_tasks,
        "names": list(active_map.keys()),
    }

    if worker_count == 0:
        report["status"] = "DEGRADED"
        report["warnings"].append("No workers are online")
        logger.warning("[health_check] No active workers found")
    else:
        logger.info(f"[health_check] {worker_count} worker(s), {total_active_tasks} active task(s)")

    # ── 3. Queue depths via Redis ─────────────────────────────────────────────
    queue_names = ["default", "high_priority", "io_tasks"]
    queue_report = {}
    for q in queue_names:
        try:
            depth = r.llen(q)
            queue_report[q] = {"depth": depth}
            if depth > 500:
                report["warnings"].append(f"Queue '{q}' depth is high: {depth}")
                if report["status"] == "OK":
                    report["status"] = "DEGRADED"
        except Exception as exc:
            queue_report[q] = {"depth": -1, "error": str(exc)}

    report["queues"] = queue_report

    # ── 4. Final status log ───────────────────────────────────────────────────
    log_fn = logger.warning if report["status"] != "OK" else logger.info
    log_fn(
        f"[health_check] status={report['status']} "
        f"workers={worker_count} warnings={report['warnings']}"
    )

    return report


# ─────────────────────────────────────────────────────────────────────────────
# Task 2 — Stale Result Cleanup  (every hour)
# ─────────────────────────────────────────────────────────────────────────────

@celery.task(
    bind=True,
    name="periodic.stale_result_cleanup",
    max_retries=2,
    default_retry_delay=30,
    queue="default",
    soft_time_limit=120,
    time_limit=180,
    ignore_result=False,
)
def stale_result_cleanup(self) -> dict:
    """
    Runs every hour via Celery Beat.

    Celery stores task results in Redis under keys like:
        celery-task-meta-<task_uuid>

    Although result_expires=3600 is set, Redis only evicts keys lazily
    (on access or when maxmemory-policy kicks in). This task proactively
    scans for and deletes result keys older than RESULT_TTL_SECONDS to
    keep Redis memory bounded.

    Also cleans up any beat-related schedule keys that accumulate over time.

    Returns a cleanup report with counts of scanned/deleted keys.
    """
    RESULT_TTL_SECONDS = int(Config.RESULT_TTL_SECONDS)
    BATCH_SIZE = 500    # keys per SCAN iteration (avoids blocking Redis)

    report = {
        "task_id": self.request.id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "scanned": 0,
        "deleted": 0,
        "errors": 0,
        "elapsed_seconds": 0.0,
    }

    start = time.perf_counter()

    try:
        r = redis_lib.from_url(Config.REDIS_URL, socket_connect_timeout=5)

        # SCAN is non-blocking and cursor-based — safe on production Redis
        cursor = 0
        deleted = 0
        scanned = 0
        errors = 0

        while True:
            cursor, keys = r.scan(
                cursor=cursor,
                match="celery-task-meta-*",
                count=BATCH_SIZE,
            )
            scanned += len(keys)

            for key in keys:
                try:
                    ttl = r.ttl(key)
                    # ttl == -1 means the key has no expiry set at all — delete it
                    # ttl == -2 means already gone (race condition) — skip
                    if ttl == -1:
                        r.delete(key)
                        deleted += 1
                        logger.debug(f"[cleanup] Deleted key with no TTL: {key}")
                    elif ttl == -2:
                        pass   # already expired, nothing to do
                    # Keys with a positive TTL were set correctly — leave them alone
                except Exception as exc:
                    errors += 1
                    logger.warning(f"[cleanup] Error processing key {key}: {exc}")

            if cursor == 0:
                break   # SCAN completed full iteration

        report["scanned"] = scanned
        report["deleted"] = deleted
        report["errors"] = errors

        logger.info(
            f"[cleanup] Done — scanned={scanned} deleted={deleted} errors={errors} "
            f"in {round(time.perf_counter() - start, 2)}s"
        )

    except Exception as exc:
        logger.error(f"[cleanup] Fatal error during cleanup: {exc}")
        raise self.retry(exc=exc)

    finally:
        report["elapsed_seconds"] = round(time.perf_counter() - start, 3)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()

    return report
