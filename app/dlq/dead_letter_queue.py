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
"""
