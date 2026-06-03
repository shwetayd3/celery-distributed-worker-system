"""
Dead-Letter Queue (DLQ) — persists permanently-failed Celery tasks.
 
Design:
  - Storage   : Redis Sorted Set  key="dlq:failed_tasks"
                Score = epoch timestamp (enables time-range queries + TTL pruning)
                Member = JSON-encoded DLQEntry
 
  - Why Redis? The broker is already Redis. No new infrastructure needed.
    For higher volumes swap the backend by replacing DLQStore._write()
    and DLQStore._read() only — the signal and API layers stay the same.
 
  - Triggered  : via Celery's task_failure signal (in signals.py).
                 Called automatically when a task exhausts all retries.
 
  - TTL        : entries older than DLQ_TTL_DAYS (default 30) are pruned
                 by the Beat periodic task dlq.prune_old_entries.
 
  - API surface (used by api.py):
      DLQStore.push(entry)                    → write one failure
      DLQStore.list(limit, offset)            → paginated list
      DLQStore.get(task_id)                   → single entry by task ID
      DLQStore.delete(task_id)                → remove after manual fix
      DLQStore.requeue(task_id, celery_app)   → re-submit to original queue
      DLQStore.stats()                        → counts by task name / queue
      DLQStore.prune(older_than_days)         → delete old entries
 
Schema (DLQEntry):
  task_id       original Celery task UUID
  task_name     dotted task name  e.g. "compute.sum_of_squares"
  queue         queue the task was running on
  args          positional arguments (JSON-safe)
  kwargs        keyword arguments   (JSON-safe)
  retries       how many times it was retried before giving up
  exception     exception class name
  traceback     full traceback string
  failed_at     ISO-8601 UTC timestamp
  worker        worker hostname that ran the final attempt
  score         same as failed_at epoch — used as the sorted-set score

"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional
 
import redis as redis_lib
 
from config.app_config import Config
 
logger = logging.getLogger(__name__)
 
# Redis key for the sorted set that holds all DLQ entries
DLQ_KEY = "dlq:failed_tasks"
# Secondary index: task_id → score, for O(1) lookup by task ID
DLQ_INDEX_KEY = "dlq:task_id_index"
 
 
# ── Data model ────────────────────────────────────────────────────────────────
 
@dataclass
class DLQEntry:
    task_id:    str
    task_name:  str
    queue:      str
    args:       list
    kwargs:     dict
    retries:    int
    exception:  str
    traceback:  str
    failed_at:  str               # ISO-8601 UTC
    worker:     str
    score:      float = field(default_factory=time.time)   # epoch seconds
 
    def to_dict(self) -> dict:
        return asdict(self)
 
    def to_json(self) -> str:
        return json.dumps(self.to_dict())
 
    @classmethod
    def from_dict(cls, d: dict) -> "DLQEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
 
    @classmethod
    def from_json(cls, s: str | bytes) -> "DLQEntry":
        return cls.from_dict(json.loads(s))
 
# ── Store ─────────────────────────────────────────────────────────────────────
 
class DLQStore:
    """
    Redis-backed Dead-Letter Queue store.
 
    All methods are class methods — no instance state needed since
    the Redis connection is stateless and created per-call.
    """
 
    # ── Connection ─────────────────────────────────────────────────────────────
 
    @classmethod
    def _redis(cls) -> redis_lib.Redis:
        return redis_lib.from_url(
            Config.REDIS_URL,
            socket_connect_timeout=3,
            decode_responses=True,
        )
 
    # ── Write ──────────────────────────────────────────────────────────────────
 
    @classmethod
    def push(cls, entry: DLQEntry) -> bool:
        """
        Persist a failed task entry to the DLQ.
 
        Uses a pipeline so both the sorted-set write and the index write
        are atomic — no partial state if Redis goes down between the two.
 
        Returns True on success, False on error (fail-safe: never raises
        so a DLQ write failure doesn't crash the worker signal handler).
        """
        try:
            r = cls._redis()
            pipe = r.pipeline(transaction=True)
            # Sorted set: score=epoch for time-range queries
            pipe.zadd(DLQ_KEY, {entry.to_json(): entry.score})
            # Index: task_id → score for O(1) delete/lookup
            pipe.hset(DLQ_INDEX_KEY, entry.task_id, entry.score)
            pipe.execute()
            logger.info(
                f"[DLQ] Persisted failed task  task_id={entry.task_id} "
                f"task={entry.task_name}  retries={entry.retries}"
            )
            return True
        except Exception as exc:
            logger.error(f"[DLQ] Failed to persist entry {entry.task_id}: {exc}")
            return False
 
    # ── Read ───────────────────────────────────────────────────────────────────
 
    @classmethod
    def list(cls, limit: int = 50, offset: int = 0) -> list[dict]:
        """
        Return paginated DLQ entries, newest first.
 
        Args:
            limit:  max entries to return (capped at 200)
            offset: how many entries to skip (for pagination)
        """
        limit = min(limit, 200)
        try:
            r = cls._redis()
            # ZREVRANGE: highest score (most recent) first
            raw_entries = r.zrevrange(DLQ_KEY, offset, offset + limit - 1)
            return [json.loads(e) for e in raw_entries]
        except Exception as exc:
            logger.error(f"[DLQ] list() failed: {exc}")
            return []
 
    @classmethod
    def get(cls, task_id: str) -> Optional[dict]:
        """
        Retrieve a single DLQ entry by its original Celery task ID.
        Returns None if not found.
        """
        try:
            r = cls._redis()
            score = r.hget(DLQ_INDEX_KEY, task_id)
            if score is None:
                return None
            score = float(score)
            # ZRANGEBYSCORE with exact score to find the matching member
            members = r.zrangebyscore(DLQ_KEY, score, score)
            for raw in members:
                entry = json.loads(raw)
                if entry.get("task_id") == task_id:
                    return entry
            return None
        except Exception as exc:
            logger.error(f"[DLQ] get({task_id}) failed: {exc}")
            return None
 
    @classmethod
    def count(cls) -> int:
        """Return total number of entries in the DLQ."""
        try:
            return cls._redis().zcard(DLQ_KEY)
        except Exception as exc:
            logger.error(f"[DLQ] count() failed: {exc}")
            return -1
 
    @classmethod
    def stats(cls) -> dict:
        """
        Return summary statistics over all DLQ entries:
          - total count
          - breakdown by task_name
          - breakdown by queue
          - oldest and newest failure timestamps
        """
        try:
            r = cls._redis()
            all_raw = r.zrange(DLQ_KEY, 0, -1, withscores=True)
            if not all_raw:
                return {"total": 0, "by_task": {}, "by_queue": {}, "oldest": None, "newest": None}
 
            by_task: dict[str, int] = {}
            by_queue: dict[str, int] = {}
            scores = []
 
            for raw, score in all_raw:
                try:
                    entry = json.loads(raw)
                    tn = entry.get("task_name", "unknown")
                    q  = entry.get("queue",     "unknown")
                    by_task[tn]  = by_task.get(tn, 0) + 1
                    by_queue[q]  = by_queue.get(q, 0) + 1
                    scores.append(score)
                except Exception:
                    continue
 
            return {
                "total":    len(all_raw),
                "by_task":  by_task,
                "by_queue": by_queue,
                "oldest":   datetime.fromtimestamp(min(scores), tz=timezone.utc).isoformat(),
                "newest":   datetime.fromtimestamp(max(scores), tz=timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.error(f"[DLQ] stats() failed: {exc}")
            return {"error": str(exc)}
     
    # ── Delete ─────────────────────────────────────────────────────────────────
 
    @classmethod
    def delete(cls, task_id: str) -> bool:
        """
        Remove a single entry from the DLQ by task_id.
        Call this after manually resolving the failure.
        Returns True if deleted, False if not found or on error.
        """
        try:
            r = cls._redis()
            score = r.hget(DLQ_INDEX_KEY, task_id)
            if score is None:
                logger.warning(f"[DLQ] delete({task_id}): not found in index")
                return False
 
            score = float(score)
            members = r.zrangebyscore(DLQ_KEY, score, score)
            deleted = 0
            pipe = r.pipeline(transaction=True)
            for raw in members:
                entry = json.loads(raw)
                if entry.get("task_id") == task_id:
                    pipe.zrem(DLQ_KEY, raw)
                    pipe.hdel(DLQ_INDEX_KEY, task_id)
                    deleted += 1
            pipe.execute()
 
            if deleted:
                logger.info(f"[DLQ] Deleted entry task_id={task_id}")
                return True
            return False
        except Exception as exc:
            logger.error(f"[DLQ] delete({task_id}) failed: {exc}")
            return False
 
    @classmethod
    def prune(cls, older_than_days: int = 30) -> int:
        """
        Delete all DLQ entries older than `older_than_days` days.
        Called by the Beat periodic task dlq.prune_old_entries.
        Returns the number of entries deleted.
        """
        try:
            r = cls._redis()
            cutoff = time.time() - (older_than_days * 86400)
 
            # Fetch members that will be pruned so we can clean the index too
            old_members = r.zrangebyscore(DLQ_KEY, "-inf", cutoff)
            if not old_members:
                return 0
 
            pipe = r.pipeline(transaction=True)
            # Remove from sorted set
            pipe.zremrangebyscore(DLQ_KEY, "-inf", cutoff)
            # Clean index entries
            for raw in old_members:
                try:
                    entry = json.loads(raw)
                    pipe.hdel(DLQ_INDEX_KEY, entry.get("task_id", ""))
                except Exception:
                    pass
            pipe.execute()
 
            logger.info(f"[DLQ] Pruned {len(old_members)} entries older than {older_than_days}d")
            return len(old_members)
        except Exception as exc:
            logger.error(f"[DLQ] prune() failed: {exc}")
            return 0
 
    
 
