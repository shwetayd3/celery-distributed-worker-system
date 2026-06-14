"""
tests/test_dlq.py
 
Tests for the Dead-Letter Queue system.
 
Covers:
  DLQStore:
    - push() writes entry to Redis sorted set + index
    - push() returns False (not raises) on Redis error
    - list() returns entries newest-first
    - list() respects limit and offset
    - get() returns correct entry by task_id
    - get() returns None for unknown task_id
    - count() returns correct total
    - delete() removes entry and index
    - delete() returns False for unknown task_id
    - prune() deletes old entries, keeps recent ones
    - prune() cleans up index for deleted entries
    - requeue() sends task back to Celery and deletes DLQ entry
    - requeue() returns None if entry not found
    - stats() returns correct by_task and by_queue breakdowns
 
  Signals:
    - task_failure signal writes to DLQ with correct fields
    - task_failure with non-serializable args uses repr fallback
    - task_retry signal does NOT write to DLQ
 
  DLQ API endpoints:
    - GET  /dlq           → 200, paginated list
    - GET  /dlq/stats     → 200, stats dict
    - GET  /dlq/<id>      → 200, single entry
    - GET  /dlq/<id>      → 404 for unknown id
    - DELETE /dlq/<id>    → 200, deleted
    - DELETE /dlq/<id>    → 404 for unknown id
    - POST /dlq/<id>/requeue → 200, new_task_id
    - POST /dlq/<id>/requeue → 400 if entry missing
    - All DLQ endpoints require admin key
 
  Beat schedule:
    - dlq-prune-daily entry exists in beat_schedule
    - prune task is routed to default queue
 
Run with: pytest tests/test_dlq.py -v
"""

import json
import time
import pytest
from unittest.mock import patch, MagicMock, call
from dataclasses import asdict
 
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
 
from app.dlq.dead_letter_queue import DLQStore, DLQEntry, DLQ_KEY, DLQ_INDEX_KEY


# ── Helpers ───────────────────────────────────────────────────────────────────
 
def make_entry(**overrides) -> DLQEntry:
    defaults = dict(
        task_id   = "task-uuid-001",
        task_name = "compute.sum_of_squares",
        queue     = "high_priority",
        args      = [1000],
        kwargs    = {},
        retries   = 3,
        exception = "RuntimeError: boom",
        traceback = "Traceback (most recent call last):\n  ...",
        failed_at = "2024-06-01T12:00:00+00:00",
        worker    = "worker-default@host",
        score     = 1717243200.0,
    )
    defaults.update(overrides)
    return DLQEntry(**defaults)
 
 
def make_redis_mock():
    return MagicMock()
 
 
