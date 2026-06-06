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
  
