"""
celery_config.py
All Celery configuration in one place.
Imported via celery.config_from_object().
"""
from kombu import Queue, Exchange

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
# Uncomment and add tasks here to use celery beat for cron-style scheduling.
# beat_schedule = {
#     "health-check-every-minute": {
#         "task": "sample.add",
#         "schedule": 60.0,
#         "args": (1, 1),
#     },
# }

# ── Worker Settings ──────────────────────────────────────────────────────────
worker_max_tasks_per_child = 200   # Recycle workers after 200 tasks (prevent memory leaks)
worker_max_memory_per_child = 512000  # 512 MB memory cap per child process

# ── Timezone ─────────────────────────────────────────────────────────────────
timezone = "UTC"
enable_utc = True

# ── Logging ──────────────────────────────────────────────────────────────────
worker_hijack_root_logger = False   # Let the app configure its own logging
worker_log_color = True
