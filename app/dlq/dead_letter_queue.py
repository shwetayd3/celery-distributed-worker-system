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
