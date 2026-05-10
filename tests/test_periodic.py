"""
Unit tests for Celery Beat periodic tasks.

Covers:
  - system_health_check: Redis reachable → OK status
  - system_health_check: Redis down → DOWN status, early return
  - system_health_check: no workers → DEGRADED status
  - system_health_check: high queue depth → DEGRADED + warning
  - system_health_check: high Redis latency → warning (still OK)
  - stale_result_cleanup: deletes keys with no TTL (ttl == -1)
  - stale_result_cleanup: leaves keys with valid TTL alone
  - stale_result_cleanup: handles per-key errors gracefully
  - stale_result_cleanup: retries on fatal Redis error
  - beat_schedule: both tasks present and correctly configured
  - beat_schedule: crontab schedule parses correctly

Run with: pytest tests/test_periodic.py -v
"""
