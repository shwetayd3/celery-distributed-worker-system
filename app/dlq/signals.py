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

import logging
import traceback as tb_module
from datetime import datetime, timezone

from celery.signals import task_failure, task_retry
from app.dlq.dead_letter_queue import DLQStore, DLQEntry

logger = logging.getLogger(__name__)

@task_failure.connect
def on_task_failure(
    sender,
    task_id,
    exception,
    args,
    kwargs,
    traceback,
    einfo,
    **extras,
):
    """
    Fired when a task fails permanently (all retries exhausted, or
    an unhandled exception with no retry).

    sender   : the task class instance
    task_id  : Celery UUID string
    exception: the exception object that caused the failure
    args     : positional args the task was called with
    kwargs   : keyword args the task was called with
    traceback: traceback object
    einfo    : ExceptionInfo object (has .traceback string)
    """
    # Determine how many retries were attempted
    retries = getattr(sender.request, "retries", 0)

    # Format the traceback as a plain string
    if einfo is not None:
        traceback_str = str(einfo.traceback)
    elif traceback is not None:
        traceback_str = "".join(tb_module.format_tb(traceback))
    else:
        traceback_str = ""

    # Determine which queue this task was running on
    delivery_info = getattr(sender.request, "delivery_info", {}) or {}
    queue = delivery_info.get("routing_key", "unknown")

    # Worker hostname
    worker = getattr(sender.request, "hostname", "unknown") or "unknown"

    # Sanitize args/kwargs — make sure they are JSON-serializable
    safe_args   = _safe_serialize(args)
    safe_kwargs = _safe_serialize(kwargs)

    entry = DLQEntry(
        task_id   = task_id,
        task_name = sender.name,
        queue     = queue,
        args      = safe_args,
        kwargs    = safe_kwargs,
        retries   = retries,
        exception = f"{type(exception).__name__}: {exception}",
        traceback = traceback_str,
        failed_at = datetime.now(timezone.utc).isoformat(),
        worker    = worker,
    )

    success = DLQStore.push(entry)

    if success:
        logger.warning(
            f"[DLQ signal] Task permanently failed → written to DLQ  "
            f"task={sender.name}  task_id={task_id}  "
            f"retries={retries}  exception={type(exception).__name__}"
        )
    else:
        # DLQ write failed — log at ERROR so it gets picked up by alerting
        logger.error(
            f"[DLQ signal] FAILED to write to DLQ  "
            f"task={sender.name}  task_id={task_id}  "
            f"exception={exception}"
        )

