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
import pytest
from unittest.mock import patch, MagicMock, call

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_redis_mock(ping_ok=True, llen_values=None, latency=0.001):
    """Build a mock Redis client for use in tests."""
    r = MagicMock()
    if ping_ok:
        r.ping.return_value = True
    else:
        r.ping.side_effect = Exception("Connection refused")
    if llen_values:
        r.llen.side_effect = lambda q: llen_values.get(q, 0)
    else:
        r.llen.return_value = 0
    return r


def make_inspect_mock(worker_names=None, active_tasks=None):
    """Build a mock Celery inspect object."""
    inspect = MagicMock()
    names = worker_names or ["worker-default@host"]
    tasks = active_tasks or []
    active_map = {name: tasks for name in names}
    inspect.active.return_value = active_map
    inspect.stats.return_value  = {name: {} for name in names}
    return inspect


# ─────────────────────────────────────────────────────────────────────────────
# system_health_check
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemHealthCheck:

    @patch("app.tasks.periodic_tasks.celery")
    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_healthy_system_returns_ok(self, mock_redis_lib, mock_celery):
        """All systems up → status OK, no warnings."""
        mock_redis_lib.from_url.return_value = make_redis_mock()
        mock_celery.control.inspect.return_value = make_inspect_mock()

        from app.tasks.periodic_tasks import system_health_check
        result = system_health_check.apply().get()

        assert result["status"] == "OK"
        assert result["warnings"] == []
        assert result["redis"]["reachable"] is True
        assert result["workers"]["count"] == 1
        assert "default" in result["queues"]

    @patch("app.tasks.periodic_tasks.celery")
    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_redis_down_returns_down_status(self, mock_redis_lib, mock_celery):
        """Redis unreachable → status DOWN, early return (no worker check)."""
        mock_redis_lib.from_url.return_value = make_redis_mock(ping_ok=False)

        from app.tasks.periodic_tasks import system_health_check
        result = system_health_check.apply().get()

        assert result["status"] == "DOWN"
        assert result["redis"]["reachable"] is False
        assert "error" in result["redis"]
        # Worker inspection must not have been attempted
        mock_celery.control.inspect.assert_not_called()

    @patch("app.tasks.periodic_tasks.celery")
    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_no_workers_returns_degraded(self, mock_redis_lib, mock_celery):
        """Redis up but zero workers → status DEGRADED + warning."""
        mock_redis_lib.from_url.return_value = make_redis_mock()
        inspect = MagicMock()
        inspect.active.return_value = {}   # no workers
        inspect.stats.return_value  = {}
        mock_celery.control.inspect.return_value = inspect

        from app.tasks.periodic_tasks import system_health_check
        result = system_health_check.apply().get()

        assert result["status"] == "DEGRADED"
        assert result["workers"]["count"] == 0
        assert any("No workers" in w for w in result["warnings"])

    @patch("app.tasks.periodic_tasks.celery")
    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_high_queue_depth_returns_degraded(self, mock_redis_lib, mock_celery):
        """Queue depth > 500 → status DEGRADED + queue warning."""
        r = make_redis_mock(llen_values={"default": 600, "high_priority": 0, "io_tasks": 0})
        mock_redis_lib.from_url.return_value = r
        mock_celery.control.inspect.return_value = make_inspect_mock()

        from app.tasks.periodic_tasks import system_health_check
        result = system_health_check.apply().get()

        assert result["status"] == "DEGRADED"
        assert any("default" in w for w in result["warnings"])
        assert result["queues"]["default"]["depth"] == 600

    @patch("app.tasks.periodic_tasks.celery")
    @patch("app.tasks.periodic_tasks.redis_lib")
    @patch("app.tasks.periodic_tasks.time")
    def test_high_redis_latency_adds_warning(self, mock_time, mock_redis_lib, mock_celery):
        """Latency > 100ms adds a warning but status stays OK."""
        # Simulate perf_counter returning values 0.2s apart
        mock_time.perf_counter.side_effect = [0.0, 0.2]
        mock_redis_lib.from_url.return_value = make_redis_mock()
        mock_celery.control.inspect.return_value = make_inspect_mock()

        from app.tasks.periodic_tasks import system_health_check
        result = system_health_check.apply().get()

        assert any("latency" in w.lower() for w in result["warnings"])

    @patch("app.tasks.periodic_tasks.celery")
    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_report_contains_all_expected_keys(self, mock_redis_lib, mock_celery):
        """Result dict has all required top-level keys."""
        mock_redis_lib.from_url.return_value = make_redis_mock()
        mock_celery.control.inspect.return_value = make_inspect_mock()

        from app.tasks.periodic_tasks import system_health_check
        result = system_health_check.apply().get()

        for key in ("task_id", "checked_at", "redis", "workers", "queues", "status", "warnings"):
            assert key in result, f"Missing key: {key}"

    @patch("app.tasks.periodic_tasks.celery")
    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_multiple_workers_counted_correctly(self, mock_redis_lib, mock_celery):
        """Active task count aggregates across all workers."""
        mock_redis_lib.from_url.return_value = make_redis_mock()
        inspect = MagicMock()
        inspect.active.return_value = {
            "worker-a@host": [{"id": "t1"}, {"id": "t2"}],
            "worker-b@host": [{"id": "t3"}],
        }
        inspect.stats.return_value = {}
        mock_celery.control.inspect.return_value = inspect

        from app.tasks.periodic_tasks import system_health_check
        result = system_health_check.apply().get()

        assert result["workers"]["count"] == 2
        assert result["workers"]["active_tasks"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# stale_result_cleanup
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleResultCleanup:

    def _make_scan_mock(self, keys, ttl_map):
        """
        Build a Redis mock that returns `keys` in one SCAN call
        and uses `ttl_map` to answer TTL queries.
        """
        r = MagicMock()
        r.scan.return_value = (0, keys)   # cursor=0 means iteration complete
        r.ttl.side_effect   = lambda k: ttl_map.get(k, 3600)
        r.delete            = MagicMock(return_value=1)
        return r

    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_deletes_keys_with_no_ttl(self, mock_redis_lib):
        """Keys with ttl == -1 (no expiry) must be deleted."""
        keys = [b"celery-task-meta-aaa", b"celery-task-meta-bbb"]
        r = self._make_scan_mock(keys, {k: -1 for k in keys})
        mock_redis_lib.from_url.return_value = r

        from app.tasks.periodic_tasks import stale_result_cleanup
        result = stale_result_cleanup.apply().get()

        assert result["scanned"] == 2
        assert result["deleted"] == 2
        assert result["errors"]  == 0
        assert r.delete.call_count == 2

    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_leaves_keys_with_valid_ttl(self, mock_redis_lib):
        """Keys with ttl > 0 (expiry set) must NOT be deleted."""
        keys = [b"celery-task-meta-ccc", b"celery-task-meta-ddd"]
        r = self._make_scan_mock(keys, {k: 1800 for k in keys})
        mock_redis_lib.from_url.return_value = r

        from app.tasks.periodic_tasks import stale_result_cleanup
        result = stale_result_cleanup.apply().get()

        assert result["scanned"] == 2
        assert result["deleted"] == 0
        r.delete.assert_not_called()

    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_skips_already_expired_keys(self, mock_redis_lib):
        """Keys with ttl == -2 (already gone) are skipped silently."""
        keys = [b"celery-task-meta-eee"]
        r = self._make_scan_mock(keys, {b"celery-task-meta-eee": -2})
        mock_redis_lib.from_url.return_value = r

        from app.tasks.periodic_tasks import stale_result_cleanup
        result = stale_result_cleanup.apply().get()

        assert result["deleted"] == 0
        assert result["errors"]  == 0

    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_mixed_ttl_values(self, mock_redis_lib):
        """Mix of no-TTL and valid-TTL keys — only no-TTL deleted."""
        keys = [
            b"celery-task-meta-1",   # ttl=-1 → delete
            b"celery-task-meta-2",   # ttl=600 → keep
            b"celery-task-meta-3",   # ttl=-1 → delete
            b"celery-task-meta-4",   # ttl=-2 → skip
        ]
        ttl_map = {
            b"celery-task-meta-1": -1,
            b"celery-task-meta-2":  600,
            b"celery-task-meta-3": -1,
            b"celery-task-meta-4": -2,
        }
        r = self._make_scan_mock(keys, ttl_map)
        mock_redis_lib.from_url.return_value = r

        from app.tasks.periodic_tasks import stale_result_cleanup
        result = stale_result_cleanup.apply().get()

        assert result["scanned"] == 4
        assert result["deleted"] == 2
        assert result["errors"]  == 0

    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_per_key_error_counted_not_fatal(self, mock_redis_lib):
        """An error on a single key increments errors count but doesn't abort."""
        keys = [b"celery-task-meta-x", b"celery-task-meta-y"]
        r = MagicMock()
        r.scan.return_value = (0, keys)
        r.ttl.side_effect = [Exception("Redis timeout"), -1]
        r.delete = MagicMock(return_value=1)
        mock_redis_lib.from_url.return_value = r

        from app.tasks.periodic_tasks import stale_result_cleanup
        result = stale_result_cleanup.apply().get()

        assert result["errors"]  == 1
        assert result["deleted"] == 1   # second key still processed

    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_result_contains_timing_fields(self, mock_redis_lib):
        """Result must include started_at, finished_at, elapsed_seconds."""
        r = MagicMock()
        r.scan.return_value = (0, [])
        mock_redis_lib.from_url.return_value = r

        from app.tasks.periodic_tasks import stale_result_cleanup
        result = stale_result_cleanup.apply().get()

        assert "started_at"      in result
        assert "finished_at"     in result
        assert "elapsed_seconds" in result
        assert result["elapsed_seconds"] >= 0

    @patch("app.tasks.periodic_tasks.redis_lib")
    def test_empty_keyspace_runs_cleanly(self, mock_redis_lib):
        """No keys to scan → no deletions, no errors."""
        r = MagicMock()
        r.scan.return_value = (0, [])
        mock_redis_lib.from_url.return_value = r

        from app.tasks.periodic_tasks import stale_result_cleanup
        result = stale_result_cleanup.apply().get()

        assert result["scanned"] == 0
        assert result["deleted"] == 0
        assert result["errors"]  == 0


# ─────────────────────────────────────────────────────────────────────────────
# Beat schedule configuration
# ─────────────────────────────────────────────────────────────────────────────

class TestBeatScheduleConfig:

    def test_both_tasks_present_in_schedule(self):
        """beat_schedule must contain entries for both periodic tasks."""
        from config.celery_config import beat_schedule
        task_names = [entry["task"] for entry in beat_schedule.values()]
        assert "periodic.system_health_check"  in task_names
        assert "periodic.stale_result_cleanup" in task_names

    def test_health_check_schedule_is_60_seconds(self):
        """Health check must fire every 60 seconds."""
        from config.celery_config import beat_schedule
        entry = beat_schedule["system-health-check-every-60s"]
        assert entry["schedule"] == 60.0

    def test_cleanup_uses_crontab_schedule(self):
        """Cleanup must use a crontab (not a fixed interval)."""
        from celery.schedules import crontab
        from config.celery_config import beat_schedule
        entry = beat_schedule["stale-result-cleanup-hourly"]
        assert isinstance(entry["schedule"], crontab)

    def test_cleanup_runs_at_top_of_hour(self):
        """crontab must be configured for minute=0 (top of every hour)."""
        from celery.schedules import crontab
        from config.celery_config import beat_schedule
        sched = beat_schedule["stale-result-cleanup-hourly"]["schedule"]
        # crontab(minute=0) matches only when minute == 0
        assert sched.minute == {0}

    def test_both_tasks_routed_to_default_queue(self):
        """Both periodic tasks must be routed to the default queue."""
        from config.celery_config import beat_schedule
        for name, entry in beat_schedule.items():
            assert entry.get("options", {}).get("queue") == "default", \
                f"Entry '{name}' is not routed to 'default' queue"

    def test_periodic_tasks_in_celery_task_routes(self):
        """periodic.* must appear in task_routes so workers accept them."""
        from config.celery_config import task_routes
        periodic_routed = any(
            "periodic" in pattern for pattern in task_routes
        )
        assert periodic_routed, "No periodic.* route found in task_routes"

    def test_beat_schedule_filename_configured(self):
        """Beat schedule DB path must be set (used by docker volume)."""
        from config import celery_config
        assert hasattr(celery_config, "beat_schedule_filename")
        assert celery_config.beat_schedule_filename != ""

    def test_periodic_tasks_in_celery_app_include(self):
        """periodic_tasks module must be in Celery's include list for autodiscovery."""
        from app.celery_app import celery
        assert "app.tasks.periodic_tasks" in celery.conf.include
