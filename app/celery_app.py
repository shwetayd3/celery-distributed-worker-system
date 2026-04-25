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
        ],
    )
    celery.config_from_object("config.celery_config")
    return celery
 
celery = create_celery_app()
