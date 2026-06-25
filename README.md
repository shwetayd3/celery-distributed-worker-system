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

## Architecture

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

## Project Structure

```
celery-distributed-worker-system/
├── app/
│   ├── __init__.py
│   ├── api.py                  # Flask REST API
│   ├── celery_app.py           # Celery app config and initialization
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── compute_tasks.py    # CPU-heavy computation tasks
│   │   ├── io_tasks.py         # I/O-bound tasks (file, network)
│   │   └── sample_tasks.py     # Demo tasks for testing
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
├── config/
│   ├── celery_config.py        # Queue routing, retry policy, rate limits
│   └── app_config.py           # Flask and Redis config
├── monitoring/
│   └── flower_config.py        # Flower authentication and settings
├── scripts/
│   ├── start_worker.sh         # Start a Celery worker
│   ├── start_flower.sh         # Start Flower dashboard
│   └── submit_sample_tasks.py  # Test script to enqueue sample tasks
├── tests/
│   ├── test_tasks.py
│   └── test_api.py
├── docker/
│   ├── Dockerfile.worker
│   └── Dockerfile.api
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Tech Stack

| Component      | Technology              |
|----------------|-------------------------|
| Task Queue     | Celery 5.x              |
| Broker         | Redis 7.x               |
| Result Backend | Redis 7.x               |
| API            | Flask + Gunicorn         |
| Monitoring     | Flower                  |
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

This starts:
- Redis on `localhost:6379`
- Flask API on `localhost:5000`
- 2 Celery workers (default and high-priority queues)
- Flower dashboard on `localhost:5555`

### Run Manually (without Docker)

```bash
# Terminal 1 — Start Redis
redis-server

# Terminal 2 — Start Celery worker (default queue)
bash scripts/start_worker.sh default

# Terminal 3 — Start Celery worker (high-priority queue)
bash scripts/start_worker.sh high_priority

# Terminal 4 — Start Flower
bash scripts/start_flower.sh

# Terminal 5 — Start Flask API
flask --app app/api.py run
```

---

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

### Run sample tasks

```bash
python scripts/submit_sample_tasks.py
```

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
