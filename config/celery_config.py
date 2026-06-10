"""
All Celery configuration in one place.
Imported via celery.config_from_object().
"""
from kombu import Queue, Exchange
from celery.schedules import crontab

# ── Broker & Backend ─────────────────────────────────────────────────────────
# Set via environment; falls back to localhost defaults.
# Override using REDIS_URL env var in production.

broker_url = "redis://localhost:6379/0"
result_backend = "redis://localhost:6379/0"

# ── Queues & Routing ─────────────────────────────────────────────────────────
default_exchange = Exchange("default", type="direct")
priority_exchange = Exchange("priority", type="direct")
io_exchange = Exchange("io", type="direct")

task_queues = (
    Queue("default",       default_exchange,  routing_key="default"),
    Queue("high_priority", priority_exchange, routing_key="high_priority"),
    Queue("io_tasks",      io_exchange,       routing_key="io_tasks"),
)

task_default_queue = "default"
task_default_exchange = "default"
task_default_routing_key = "default"

task_routes = {
    # Compute-heavy tasks → high_priority workers
    "compute.*":                        {"queue": "high_priority"},
    "app.tasks.compute_tasks.*":        {"queue": "high_priority"},

    # I/O-bound tasks → io_tasks workers
    "io.*":                             {"queue": "io_tasks"},
    "app.tasks.io_tasks.*":             {"queue": "io_tasks"},

    # Sample/demo tasks → default workers
    "sample.*":                         {"queue": "default"},
    "app.tasks.sample_tasks.*":         {"queue": "default"},

    "periodic.*":                 {"queue": "default"},
    "app.tasks.periodic_tasks.*": {"queue": "default"},
    "dlq.*":                      {"queue": "default"},
    "app.tasks.dlq_tasks.*":      {"queue": "default"},
}

# ── Serialization ────────────────────────────────────────────────────────────
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]

# ── Result Settings ──────────────────────────────────────────────────────────
result_expires = 3600          # Results expire after 1 hour
result_persistent = True       # Persist results in Redis across restarts

# ── Task Behavior ────────────────────────────────────────────────────────────
task_acks_late = True          # Acknowledge only after task completes (safer)
task_reject_on_worker_lost = True  # Re-queue if a worker dies mid-task
worker_prefetch_multiplier = 1     # One task at a time per worker (fair dispatch)

# ── Time Limits ──────────────────────────────────────────────────────────────
task_soft_time_limit = 300     # Raise SoftTimeLimitExceeded at 5 minutes
task_time_limit = 360          # Kill task at 6 minutes (hard limit)

# ── Retry Defaults ───────────────────────────────────────────────────────────
task_max_retries = 3
task_default_retry_delay = 5   # seconds

# ── Beat Scheduler (periodic tasks) ─────────────────────────────────────────
# Celery Beat reads this schedule and enqueues tasks at the configured interval.
# Run Beat with: bash scripts/start_beat.sh
# Beat requires exactly ONE running instance — never scale it horizontally.
from celery.schedules import crontab

beat_schedule = {
    # ── Task 1: System health check — every 60 seconds ─────────────────────
    # Pings Redis, inspects active workers, measures queue depths.
    # Results are stored in Redis so /health can surface them without extra load.
    "system-health-check-every-60s": {
        "task": "periodic.system_health_check",
        "schedule": 60.0,                    # float = seconds interval
        "options": {"queue": "default"},
    },

    # ── Task 2: Stale result cleanup — every hour at :00 ───────────────────
    # Scans Redis for Celery result keys with no TTL and deletes them.
    # Keeps Redis memory bounded without relying on maxmemory-policy alone.
    "stale-result-cleanup-hourly": {
        "task": "periodic.stale_result_cleanup",
        "schedule": crontab(minute=0),       # crontab = "at the top of every hour"
        "options": {"queue": "default"},
    },

    # Task 3: DLQ prune — daily at 02:00 UTC
    # Deletes DLQ entries older than DLQ_TTL_DAYS (default 30).
    # Runs at an off-peak hour to minimise Redis contention.
    "dlq-prune-daily": {
        "task":    "dlq.prune_old_entries",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "default"},
        "options": {"queue": "default"},
    },
}

# Where Beat stores the schedule database (tracks last-run times).
# Use a mounted volume in Docker so it survives container restarts.
beat_scheduler = "django_celery_beat.schedulers:DatabaseScheduler"  # swap to DB scheduler if needed

beat_schedule_filename = "/var/run/celery/celerybeat-schedule"
beat_max_loop_interval = 5   # seconds between Beat's internal loop ticks

# ── Worker Settings ──────────────────────────────────────────────────────────
worker_max_tasks_per_child = 200   # Recycle workers after 200 tasks (prevent memory leaks)
worker_max_memory_per_child = 512000  # 512 MB memory cap per child process

# ── Timezone ─────────────────────────────────────────────────────────────────
timezone = "UTC"
enable_utc = True

# ── Logging ──────────────────────────────────────────────────────────────────
worker_hijack_root_logger = False   # Let the app configure its own logging
worker_log_color = True

