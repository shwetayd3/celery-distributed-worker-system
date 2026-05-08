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
