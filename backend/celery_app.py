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
        "tasks.ai_tasks",
        "tasks.auto_sync_tasks",
        "tasks.workflow_tasks"
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
    # Periodic task schedule - Essential maintenance only
    # Gmail polling service runs independently for real-time email monitoring
    beat_schedule={
        # Keep token refresh to prevent expired tokens
        'refresh-expiring-tokens': {
            'task': 'tasks.auto_sync_tasks.refresh_expiring_tokens', 
            'schedule': 900.0,  # Run every 15 minutes - keep tokens valid
        },
        # Keep workflow maintenance for timeouts and state management
        'workflow-maintenance': {
            'task': 'tasks.workflow_tasks.workflow_maintenance',
            'schedule': 3600.0,  # Run every hour - check timeouts and cleanup
        },
        # Keep cleanup for housekeeping
        'cleanup-completed-workflows': {
            'task': 'tasks.workflow_tasks.cleanup_completed_workflows',
            'schedule': 86400.0,  # Run daily - cleanup old workflows
        },
        # Gmail polling service runs independently for real-time email monitoring
        # Email processing now handled by polling service every 10 seconds
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks()

if __name__ == "__main__":
    celery_app.start() 