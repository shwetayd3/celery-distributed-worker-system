from celery import Celery
from config.app_config import Config

def create_celery_app():
    celery = Celery(
        "celery_worker_system",
        broker=Config.REDIS_URL,
        backend=Config.REDIS_URL,
        include=[
            "app.tasks.compute_tasks",
            "app.tasks.io_tasks",
            "app.tasks.sample_tasks",
            "app.tasks.periodic_tasks",   # Beat tasks
            "app.tasks.dlq_tasks",        # DLQ prune task
        ],
    )
    celery.config_from_object("config.celery_config")
   
    # Register DLQ signal handlers — must happen after app creation
    # so the app instance exists when signals.py is imported.
   
    import app.dlq.signals  # noqa: F401  (import for side-effects only)
    return celery

celery = create_celery_app()
