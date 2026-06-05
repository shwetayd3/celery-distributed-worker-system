"""
Celery signal handlers that feed permanently-failed tasks into the DLQ.

How Celery retry vs. permanent failure works:
  - Every time a task calls self.retry(), Celery raises a Retry exception
    internally. The task_retry signal fires, but task_failure does NOT.
  - When a task raises an exception WITHOUT calling self.retry(), OR when
    self.retry() is called but max_retries has already been reached and
    Celery raises MaxRetriesExceededError, the task_failure signal fires.

So task_failure == "this task is permanently dead" — exactly when we want
to write to the DLQ.

Registration:
  Import this module once in celery_app.py after the Celery app is created.
  Signals are process-global so they only need to be registered once.
"""

