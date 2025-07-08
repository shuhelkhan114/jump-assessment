"""
Gmail Polling Tasks for background email monitoring
"""
import asyncio
import structlog
from celery import Celery
from services.gmail_polling_service import gmail_polling_service

logger = structlog.get_logger()

# Import Celery app
try:
    from celery_app import celery_app
except ImportError:
    celery_app = None
    logger.warning("Celery not available, falling back to synchronous processing")

@celery_app.task
def start_gmail_polling():
    """Start the Gmail polling service as a background task"""
    try:
        logger.info("🚀 Starting Gmail polling service via Celery task")
        
        # Create event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Start the polling service
            loop.run_until_complete(gmail_polling_service.start_polling())
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"❌ Error starting Gmail polling service: {str(e)}")
        raise

@celery_app.task
def stop_gmail_polling():
    """Stop the Gmail polling service"""
    try:
        logger.info("🛑 Stopping Gmail polling service via Celery task")
        
        # Create event loop for async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Stop the polling service
            loop.run_until_complete(gmail_polling_service.stop_polling())
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"❌ Error stopping Gmail polling service: {str(e)}")
        raise

@celery_app.task
def check_gmail_polling_status():
    """Check if Gmail polling service is running"""
    try:
        is_running = gmail_polling_service.is_running
        logger.info(f"📊 Gmail polling service status: {'Running' if is_running else 'Stopped'}")
        return {
            "status": "running" if is_running else "stopped",
            "polling_interval": gmail_polling_service.polling_interval,
            "rate_limit_delay": gmail_polling_service.rate_limit_delay
        }
    except Exception as e:
        logger.error(f"❌ Error checking Gmail polling status: {str(e)}")
        return {"status": "error", "message": str(e)} 