# celery-distributed-worker-system
A production-ready distributed task processing system built with **Celery**, **Redis**, and **Flower** featuring async workers, task routing, retry logic,API key authentication, a Beat scheduler, a Dead-Letter Queue, priority queues, and a real-time monitoring dashboard.

---

## Features

- Distributed master-slave worker architecture using Celery with 3 named queues
- Redis as the message broker and result backend
- Task routing with named queues (`default`, `high_priority`, `io_tasks`)
- Automatic retries with exponential backoff and configurable limits
- API key authentication — role-based (admin / readonly) with per-key rate limiting
- Celery Beat scheduler — periodic tasks (health check every 60s, result cleanup hourly)
- Dead-Letter Queue (DLQ) — permanently-failed tasks persisted in Redis with admin API
- Flower dashboard for real-time worker and queue monitoring
 monitoring
- REST API (Flask + Gunicorn) to submit, track, and manage tasks
- Dockerized setup for local and production use - one docker-compose up starts all 6 services
- Sample tasks: heavy computation, file processing, simulated I/O
- Test suites covering tasks, API, auth, Beat config, and DLQ (no Redis required for unit tests)

---

## Architecture Version 1

```
[Flask API] --> [Redis Broker] --> [Celery Workers (x N)]
                                        |
                              [Redis Result Backend]
                                        |
                               [Flower Dashboard]
```

- **Flask API** — accepts task submissions via HTTP, returns task IDs
- **Redis** — acts as the message broker (queue) and result store
- **Celery Workers** — pull tasks from queues and execute them asynchronously
- **Flower** — web-based monitoring for workers, queues, and task history

---

## Architecture Version 2

```
                         ┌─────────────────────────────────────────┐
                        │           Flask REST API                 │
                        │  (API key auth + rate limiting)          │
                        └────────────────┬────────────────────────┘
                                         │ submit tasks
                                         ▼
                               ┌──────────────────┐
          ┌────────────────────│   Redis Broker   │────────────────────┐
          │   default queue    └──────────────────┘  high_priority q   │
          ▼                            │                                ▼
  ┌──────────────────┐                 │ io_tasks q          ┌──────────────────┐
  │  Worker: default │                 ▼                     │ Worker: priority │
  │  (concurrency=4) │      ┌──────────────────┐            │  (concurrency=2) │
  └──────────────────┘      │  Worker: io      │            └──────────────────┘
                             │  (concurrency=8) │
                             └──────────────────┘
                                         │
                                         ▼
                               ┌──────────────────┐
                               │  Redis Result    │◄─── Flower Dashboard
                               │  Backend         │     (http://localhost:5555)
                               └────────┬─────────┘
                                        │ on permanent failure
                                        ▼
                               ┌──────────────────┐
                               │  Dead-Letter     │◄─── Admin API (/dlq/*)
                               │  Queue (Redis    │     list / get / delete
                               │  Sorted Set)     │     requeue / stats
                               └──────────────────┘
                                        ▲
                               ┌──────────────────┐
                               │  Celery Beat     │  health check (60s)
                               │  Scheduler       │  result cleanup (hourly)
                               │  (single inst.)  │  DLQ prune (daily 02:00)
                               └──────────────────┘

```

- **Flask API** — accepts task submissions via HTTP; all endpoints protected by X-API-Key auth except /health
- **Redis** — dual role: message broker (queues) and result backend; also stores the DLQ sorted set
- **Celery Workers** — 3 dedicated worker processes, each consuming one queue
- **Celery Beat** — single-instance scheduler that enqueues periodic tasks on a cron/interval cadence
- **Flower** —  web dashboard for live worker status, task history, queue depths, and failure tracebacks
- **Dead-Letter Queue** — Redis Sorted Set (dlq:failed_tasks) capturing every permanently-failed task with full traceback, args, retry count, and worker hostname; secondary Hash index for O(1) lookup by task ID


## Project Structure

```
celery-distributed-worker-system/
├── app/
│   ├── __init__.py
│   ├── api.py                  # Flask REST API — 20 endpoints
│   ├── celery_app.py           # Celery app config and initialization
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── compute_tasks.py    # CPU-heavy computation tasks → high_priority 
│   │   ├── io_tasks.py         # I/O-bound tasks (file, network) → io_tasks queue
│   │   └── sample_tasks.py     # Demo tasks for testing (chains, groups, countdown)
│   │   ├── periodic_tasks.py   # Beat tasks: health check + result cleanup
│   │   └── dlq_tasks.py        # Beat task: DLQ prune (daily)
│   │
│   ├── dlq/
│   │   ├── __init__.py
│   │   ├── dead_letter_queue.py    # DLQStore — Redis sorted set + hash index
│   │   └── signals.py              # task_failure signal → DLQ capture
│   │
│   └── utils/
│       ├── __init__.py
│       └── helpers.py          # format_bytes, retry_with_backoff, chunk_list
|
├── config/
│   ├── __init__.py
│   ├── celery_config.py        # Queue routing, retry policy, rate-time limits,Beat schedule
│   └── app_config.py           # Flask Redis, API keys, DLQ TTL config
│
├── monitoring/
│   └── flower_config.py        # Flower authentication and settings, port, persistence settings
|
├── scripts/
│   ├── start_worker.sh         # Start a Celery worker(queue + concurrency args)
│   ├── start_beat.sh           # Start Celery Beat (single instance only)
│   ├── start_flower.sh         # Start Flower dashboard
│   └── submit_sample_tasks.py  # Test script to enqueue sample tasks.End-to-end smoke test across all queues
│   └── generate_api_key.py     # CLI to generate + hash API keys
│
├── tests/
│   ├── __init__.py
│   ├── test_tasks.py        # Unit tests for all task modules
│   └── test_api.py          # Flask API endpoint tests (mocked Celery)
│   ├── test_auth.py         # Auth middleware — 24 tests
│   ├── test_periodic.py     # Beat tasks + schedule config — 19 tests
│   └── test_dlq.py          # DLQ store, signals, API, Beat — 43 tests
│
├── docker/
│   ├── Dockerfile.worker    # Image for workers, Beat, and Flower
│   └── Dockerfile.api       # Image for Flask API (Gunicorn)
├── docker-compose.yml       # 6 services: Redis, API, 3 workers, Beat, Flower
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Tech Stack

| Component      | Technology              |
|----------------|-------------------------|
| Task Queue     | Celery 5.x              |
| Broker         | Redis 7.x               |
| Result Backend | Redis 7.x               |
|Dead-Letter Queue| Redis Sorted Set + Hash  |
| API            | Flask 3.x + Gunicorn         |
|Authentication |API key (SHA-256 hashed) |
|Rate Limiting | Redis sliding-window counter|
| Monitoring     | Flower 2.x                |
| Scheduler | Celery Beat| 
| Containerization | Docker + Docker Compose |
| Language       | Python 3.10+            |

---

## Getting Started

### Prerequisites

- Docker & Docker Compose
- Python 3.10+
- Redis (or use Docker)

### Clone and Setup

```bash
git clone https://github.com/<your-username>/celery-distributed-worker-system.git
cd celery-distributed-worker-system

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run with Docker Compose

```bash
docker-compose up --build
```

This starts all 6 services:
 
| Service            | URL / Port          | Description                        |
|--------------------|---------------------|------------------------------------|
| Redis              | `localhost:6379`    | Broker + result backend + DLQ store|
| Flask API          | `localhost:5000`    | REST API with API key auth         |
| Worker (default)   | —                   | Handles `default` queue            |
| Worker (priority)  | —                   | Handles `high_priority` queue      |
| Worker (io)        | —                   | Handles `io_tasks` queue           |
| Beat scheduler     | —                   | Periodic tasks (single instance)   |
| Flower             | `localhost:5555`    | Monitoring dashboard               |
 

### Run Manually (without Docker)

```bash
# Terminal 1 — Start Redis
redis-server

# Terminal 2 — Start Celery worker (default queue)
bash scripts/start_worker.sh default 4

# Terminal 3 — Start Celery worker (high-priority queue)
bash scripts/start_worker.sh high_priority 2

# Terminal 4 — Worker: io_tasks queue
bash scripts/start_worker.sh io_tasks 8
 
# Terminal 5 — Beat scheduler (ONE instance only)
bash scripts/start_beat.sh

# Terminal 6 — Start Flower dashboard
bash scripts/start_flower.sh
 
# Terminal 7 — Start Flask API
flask --app app/api.py run
```

---
 
## API Key Authentication
 
All endpoints (except `GET /health`) require an `X-API-Key` header.
 
### Roles
 
| Role       | Access                                             |
|------------|----------------------------------------------------|
| `admin`    | Full access — submit, revoke, inspect, DLQ, reload |
| `readonly` | Task submission and status only                    |
 
### Generate a key
 
```bash
python scripts/generate_api_key.py --name "ci-pipeline" --role admin --rate-limit 120
```
 
Prints the raw key and the JSON entry to add to `API_KEYS`.
 
### Configure keys
 
```bash
export API_KEYS='[
  {"key": "your-secret-key", "name": "local-dev", "role": "admin", "rate_limit": null, "enabled": true}
]'
```

## Usage

### Submit a task via API

```bash
# Submit a compute task
curl -X POST http://localhost:5000/tasks/compute \
  -H "Content-Type: application/json" \
  -d '{"n": 100000}'

# Response
{"task_id": "d3f1a2b4-...", "status": "PENDING"}
```

### Check task status

```bash
curl http://localhost:5000/tasks/d3f1a2b4-.../status

# Response
{"task_id": "d3f1a2b4-...", "status": "SUCCESS", "result": 4999950000}
```

### Run sample tasks (smoke test)

```bash
python scripts/submit_sample_tasks.py
```

---

## Dead-Letter Queue
 
Tasks that exhaust all retries are automatically captured by the `task_failure` Celery signal and written to a Redis Sorted Set (`dlq:failed_tasks`). Each entry stores the task name, queue, original args/kwargs, retry count, full traceback, worker hostname, and failure timestamp.

### DLQ API (admin key required)
 
```bash
# List all failed tasks (newest first)
curl http://localhost:5000/dlq?limit=20 -H "X-API-Key: admin-key"
 
# Summary stats by task and queue
curl http://localhost:5000/dlq/stats -H "X-API-Key: admin-key"
 
# Get a single entry
curl http://localhost:5000/dlq/<task_id> -H "X-API-Key: admin-key"
 
# Re-submit to original queue (deletes DLQ entry on success)
curl -X POST http://localhost:5000/dlq/<task_id>/requeue -H "X-API-Key: admin-key"
 
# Delete after manual fix
curl -X DELETE http://localhost:5000/dlq/<task_id> -H "X-API-Key: admin-key"
```
 
DLQ entries older than `DLQ_TTL_DAYS` (default: 30) are pruned daily at 02:00 UTC by a Beat task.
 
---
 
## Celery Configuration Highlights

**`config/celery_config.py`**

```python
from kombu import Queue

CELERY_TASK_QUEUES = (
    Queue('default'),
    Queue('high_priority'),
    Queue('io_tasks'),
)

CELERY_TASK_DEFAULT_QUEUE = 'default'

CELERY_TASK_ROUTES = {
    'app.tasks.compute_tasks.*': {'queue': 'high_priority'},
    'app.tasks.io_tasks.*':      {'queue': 'io_tasks'},
}

CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TIMEZONE = 'UTC'
```

---

## Monitoring with Flower

Access the Flower dashboard at: **http://localhost:5555**

Dashboard features:
- Live worker status and heartbeat
- Task success/failure/retry rates
- Queue lengths per broker
- Per-task execution history and traceback on failure
- Worker pool controls (concurrency, autoscaling)

To enable basic auth on Flower:

```bash
celery --app=app.celery_app flower --basic-auth=admin:secret
```

---

## Sample Tasks

```python
# app/tasks/compute_tasks.py

from app.celery_app import celery

@celery.task(bind=True, max_retries=3, default_retry_delay=5)
def sum_of_squares(self, n):
    try:
        return sum(i * i for i in range(n))
    except Exception as exc:
        raise self.retry(exc=exc)
```

```python
# app/tasks/io_tasks.py

import time
from app.celery_app import celery

@celery.task(bind=True, queue='io_tasks')
def simulate_file_processing(self, filename):
    time.sleep(2)  # Simulate I/O wait
    return f"Processed: {filename}"
```

---

## Running Tests

```bash
pytest tests/ -v
```

Tests use `celery.contrib.pytest` with an in-memory broker so no Redis is required for unit tests.

---

## Scaling Workers

To scale the number of workers:

```bash
# Docker Compose scale
docker-compose up --scale worker=4

# Or start workers manually with concurrency
celery -A app.celery_app worker --concurrency=4 --queues=default,high_priority
```

---

## Environment Variables

| Variable           | Default               | Description                     |
|--------------------|-----------------------|---------------------------------|
| `REDIS_URL`        | `redis://localhost:6379/0` | Redis broker and backend URL |
| `FLASK_SECRET_KEY` | `changeme`            | Flask secret key                |
| `FLOWER_PORT`      | `5555`                | Flower dashboard port           |
| `WORKER_CONCURRENCY` | `4`                 | Workers per Celery process      |

Copy `.env.example` to `.env` and update values before running.

---

## Roadmap

- [x] Named queue routing (default / high_priority / io_tasks)
- [x] Retry logic with exponential backoff
- [x] Flower monitoring dashboard
- [x] API key authentication with RBAC and rate limiting per task type
- [x] Celery Beat periodic scheduler for periodic/cron tasks
- [x] Dead-Letter Queue with admin REST API for failed tasks
- [ ] Prometheus metrics exporter for Celery
- [ ] Grafana dashboard for long-term task analytics
- [ ] GitHub Actions CI/CD pipeline

---

## Contributing

Pull requests are welcome. For major changes, open an issue first to discuss what you would like to change.

---

## License

MIT
