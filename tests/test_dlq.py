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
 

# ─────────────────────────────────────────────────────────────────────────────
# DLQEntry data model
# ─────────────────────────────────────────────────────────────────────────────
 
class TestDLQEntry:
    def test_to_json_round_trip(self):
        entry = make_entry()
        restored = DLQEntry.from_json(entry.to_json())
        assert restored.task_id   == entry.task_id
        assert restored.task_name == entry.task_name
        assert restored.args      == entry.args
        assert restored.retries   == entry.retries
 
    def test_to_dict_contains_all_fields(self):
        entry = make_entry()
        d = entry.to_dict()
        for field in ("task_id", "task_name", "queue", "args", "kwargs",
                      "retries", "exception", "traceback", "failed_at", "worker", "score"):
            assert field in d, f"Missing field: {field}"
 
    def test_score_defaults_to_current_time(self):
        before = time.time()
        entry = DLQEntry(
            task_id="x", task_name="t", queue="q", args=[], kwargs={},
            retries=0, exception="E", traceback="", failed_at="", worker="w"
        )
        after = time.time()
        assert before <= entry.score <= after
 
 

# ─────────────────────────────────────────────────────────────────────────────
# DLQStore.push
# ─────────────────────────────────────────────────────────────────────────────
 
class TestDLQStorePush:
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_push_writes_to_sorted_set_and_index(self, mock_redis_lib):
        r = make_redis_mock()
        pipe = MagicMock()
        r.pipeline.return_value.__enter__ = MagicMock(return_value=pipe)
        r.pipeline.return_value = pipe
        pipe.execute.return_value = [1, 1]
        mock_redis_lib.from_url.return_value = r
 
        entry = make_entry()
        result = DLQStore.push(entry)
 
        assert result is True
        pipe.zadd.assert_called_once()
        pipe.hset.assert_called_once_with(DLQ_INDEX_KEY, entry.task_id, entry.score)
 
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_push_returns_false_on_redis_error(self, mock_redis_lib):
        mock_redis_lib.from_url.side_effect = Exception("Redis down")
        result = DLQStore.push(make_entry())
        assert result is False   # must not raise
 
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_push_stores_json_in_sorted_set(self, mock_redis_lib):
        r = make_redis_mock()
        pipe = MagicMock()
        r.pipeline.return_value = pipe
        pipe.execute.return_value = [1, 1]
        mock_redis_lib.from_url.return_value = r
 
        entry = make_entry()
        DLQStore.push(entry)
 
        zadd_call = pipe.zadd.call_args
        mapping = zadd_call[0][1]   # second positional arg is the {member: score} dict
        raw_key = list(mapping.keys())[0]
        parsed = json.loads(raw_key)
        assert parsed["task_id"]   == entry.task_id
        assert parsed["task_name"] == entry.task_name
     
 
# ─────────────────────────────────────────────────────────────────────────────
# DLQStore.list
# ─────────────────────────────────────────────────────────────────────────────
 
class TestDLQStoreList:
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_list_returns_parsed_entries(self, mock_redis_lib):
        entry = make_entry()
        r = make_redis_mock()
        r.zrevrange.return_value = [entry.to_json()]
        mock_redis_lib.from_url.return_value = r
 
        result = DLQStore.list(limit=10, offset=0)
 
        assert len(result) == 1
        assert result[0]["task_id"] == entry.task_id
        r.zrevrange.assert_called_once_with(DLQ_KEY, 0, 9)
 
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_list_respects_offset(self, mock_redis_lib):
        r = make_redis_mock()
        r.zrevrange.return_value = []
        mock_redis_lib.from_url.return_value = r
 
        DLQStore.list(limit=20, offset=40)
        r.zrevrange.assert_called_once_with(DLQ_KEY, 40, 59)
 
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_list_caps_limit_at_200(self, mock_redis_lib):
        r = make_redis_mock()
        r.zrevrange.return_value = []
        mock_redis_lib.from_url.return_value = r
 
        DLQStore.list(limit=999, offset=0)
        r.zrevrange.assert_called_once_with(DLQ_KEY, 0, 199)
 
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_list_returns_empty_on_redis_error(self, mock_redis_lib):
        mock_redis_lib.from_url.side_effect = Exception("Connection refused")
        result = DLQStore.list()
        assert result == []

 
# ─────────────────────────────────────────────────────────────────────────────
# DLQStore.get
# ─────────────────────────────────────────────────────────────────────────────
 
class TestDLQStoreGet:
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_get_returns_entry_by_task_id(self, mock_redis_lib):
        entry = make_entry()
        r = make_redis_mock()
        r.hget.return_value = str(entry.score)
        r.zrangebyscore.return_value = [entry.to_json()]
        mock_redis_lib.from_url.return_value = r
 
        result = DLQStore.get(entry.task_id)
        assert result is not None
        assert result["task_id"] == entry.task_id
 
    @patch("app.dlq.dead_letter_queue.redis_lib")
    def test_get_returns_none_for_unknown_id(self, mock_redis_lib):
        r = make_redis_mock()
        r.hget.return_value = None
        mock_redis_lib.from_url.return_value = r
 
        result = DLQStore.get("nonexistent-id")
        assert result is None
 
 
