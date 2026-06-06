"""
Celery Beat task: prune DLQ entries older than DLQ_TTL_DAYS.
 
Runs daily at 02:00 UTC via the beat_schedule in celery_config.py.
Prevents the DLQ sorted set from growing without bound.
"""

import logging
from datetime import datetime, timezone
 
from app.celery_app import celery
from app.dlq.dead_letter_queue import DLQStore
from config.app_config import Config
 
logger = logging.getLogger(__name__)
 
 
@celery.task(
    bind=True,
    name="dlq.prune_old_entries",
    max_retries=2,
    default_retry_delay=60,
    queue="default",
    ignore_result=False,
)
  
def prune_old_dlq_entries(self) -> dict:
    """
    Scheduled daily at 02:00 UTC by Celery Beat.

    Deletes DLQ entries older than Config.DLQ_TTL_DAYS (default: 30).
    Also logs current DLQ stats so the deletion is auditable in logs.
    """
 
    ttl_days = Config.DLQ_TTL_DAYS
    logger.info(f"[dlq_prune] Starting — pruning entries older than {ttl_days} days")
 
    try:
        # Snapshot stats before pruning for the audit log
        before = DLQStore.stats()
 
        deleted = DLQStore.prune(older_than_days=ttl_days)
 
        # Snapshot stats after pruning
        after = DLQStore.stats()
 
        result = {
            "task_id":       self.request.id,
            "ran_at":        datetime.now(timezone.utc).isoformat(),
            "ttl_days":      ttl_days,
            "deleted":       deleted,
            "total_before":  before.get("total", -1),
            "total_after":   after.get("total", -1),
        }
 
        logger.info(
            f"[dlq_prune] Done — deleted={deleted} "
            f"remaining={result['total_after']}"
        )
        return result
 
    except Exception as exc:
        logger.error(f"[dlq_prune] Error: {exc}")
        raise self.retry(exc=exc)
 
