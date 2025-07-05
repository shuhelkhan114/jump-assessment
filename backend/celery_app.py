from celery import Celery
from config import get_settings
import structlog

logger = structlog.get_logger()
settings = get_settings()

# Create Celery app
celery_app = Celery(
    "financial_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "tasks.gmail_tasks",
        "tasks.hubspot_tasks",
        "tasks.ai_tasks"
    ]
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    result_expires=3600,  # Results expire after 1 hour
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)

# Auto-discover tasks
celery_app.autodiscover_tasks()

@celery_app.task(bind=True)
def debug_task(self):
    logger.info(f"Request: {self.request!r}")
    return f"Hello from Celery worker!"

if __name__ == "__main__":
    celery_app.start() 