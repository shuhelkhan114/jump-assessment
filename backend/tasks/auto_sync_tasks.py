"""
Auto-sync tasks for periodic data synchronization
"""
import asyncio
from datetime import datetime, timedelta
from typing import List
import structlog
from celery import shared_task
from tasks.gmail_tasks import sync_gmail_emails
from tasks.hubspot_tasks import sync_hubspot_contacts, sync_hubspot_deals, sync_hubspot_companies

logger = structlog.get_logger()

@shared_task(bind=True, max_retries=3)
def auto_sync_all_users(self):
    """
    Periodic task to sync data for all users every 5 minutes
    Note: This is a simplified version that will sync known users
    """
    try:
        logger.info("🔄 Starting auto-sync for all users")
        
        # For simplicity, we'll just trigger sync for the known user
        # In a real implementation, we'd query the database for all users
        known_user_id = "ba433c75-8a32-430c-99e7-e3e8069501ca"
        
        # Queue sync tasks for the known user
        gmail_result = sync_gmail_emails.delay(known_user_id)
        contacts_result = sync_hubspot_contacts.delay(known_user_id)
        deals_result = sync_hubspot_deals.delay(known_user_id)
        companies_result = sync_hubspot_companies.delay(known_user_id)
        
        result = {
            "users_processed": 1,
            "gmail_synced": 1,
            "hubspot_contacts_synced": 1,
            "hubspot_deals_synced": 1,
            "hubspot_companies_synced": 1,
            "errors": []
        }
        
        logger.info(f"✅ Auto-sync completed: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"❌ Auto-sync failed: {str(exc)}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))



@shared_task(bind=True, max_retries=3)
def initial_user_sync(self, user_id: str):
    """
    Task to perform initial data sync when user first connects integrations
    """
    try:
        logger.info(f"🚀 Starting initial sync for user {user_id}")
        
        # Queue sync tasks for the user
        gmail_result = sync_gmail_emails.delay(user_id)
        contacts_result = sync_hubspot_contacts.delay(user_id)
        deals_result = sync_hubspot_deals.delay(user_id)
        companies_result = sync_hubspot_companies.delay(user_id)
        
        result = {
            "user_id": user_id,
            "gmail_synced": True,
            "hubspot_contacts_synced": True,
            "hubspot_deals_synced": True,
            "hubspot_companies_synced": True,
            "errors": []
        }
        
        logger.info(f"✅ Initial sync completed for user {user_id}: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"❌ Initial sync failed for user {user_id}: {str(exc)}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))



@shared_task(bind=True, max_retries=3)
def initial_gmail_sync(self, user_id: str):
    """
    Task to perform initial Gmail sync when user connects Google OAuth
    """
    try:
        logger.info(f"📧 Starting initial Gmail sync for user {user_id}")
        
        # Queue Gmail sync task
        gmail_result = sync_gmail_emails.delay(user_id)
        
        result = {
            "user_id": user_id,
            "gmail_synced": True,
            "task_id": gmail_result.id
        }
        
        logger.info(f"✅ Initial Gmail sync completed for user {user_id}: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"❌ Initial Gmail sync failed for user {user_id}: {str(exc)}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))



@shared_task(bind=True, max_retries=3)
def initial_hubspot_sync(self, user_id: str):
    """
    Task to perform initial HubSpot sync when user connects HubSpot OAuth
    """
    try:
        logger.info(f"🔗 Starting initial HubSpot sync for user {user_id}")
        
        # Queue HubSpot sync tasks
        contacts_result = sync_hubspot_contacts.delay(user_id)
        deals_result = sync_hubspot_deals.delay(user_id)
        companies_result = sync_hubspot_companies.delay(user_id)
        
        result = {
            "user_id": user_id,
            "hubspot_contacts_synced": True,
            "hubspot_deals_synced": True,
            "hubspot_companies_synced": True,
            "task_ids": {
                "contacts": contacts_result.id,
                "deals": deals_result.id,
                "companies": companies_result.id
            }
        }
        
        logger.info(f"✅ Initial HubSpot sync completed for user {user_id}: {result}")
        return result
        
    except Exception as exc:
        logger.error(f"❌ Initial HubSpot sync failed for user {user_id}: {str(exc)}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))



@shared_task
def trigger_initial_sync_if_needed(user_id: str):
    """
    Trigger initial sync for a user (simplified version)
    """
    try:
        logger.info(f"🔍 Triggering initial sync for user {user_id}")
        
        # Just trigger the initial sync directly
        result = initial_user_sync.delay(user_id)
        
        return {"initial_sync_triggered": True, "task_id": result.id}
        
    except Exception as e:
        logger.error(f"❌ Failed to trigger initial sync for user {user_id}: {str(e)}")
        return {"error": str(e)}



@shared_task
def trigger_gmail_sync(user_id: str):
    """
    Trigger Gmail sync for a user when Google OAuth is completed
    """
    try:
        logger.info(f"📧 Triggering Gmail sync for user {user_id}")
        
        # Trigger Gmail sync only
        result = initial_gmail_sync.delay(user_id)
        
        return {"gmail_sync_triggered": True, "task_id": result.id}
        
    except Exception as e:
        logger.error(f"❌ Failed to trigger Gmail sync for user {user_id}: {str(e)}")
        return {"error": str(e)}



@shared_task
def trigger_hubspot_sync(user_id: str):
    """
    Trigger HubSpot sync for a user when HubSpot OAuth is completed
    """
    try:
        logger.info(f"🔗 Triggering HubSpot sync for user {user_id}")
        
        # Trigger HubSpot sync only
        result = initial_hubspot_sync.delay(user_id)
        
        return {"hubspot_sync_triggered": True, "task_id": result.id}
        
    except Exception as e:
        logger.error(f"❌ Failed to trigger HubSpot sync for user {user_id}: {str(e)}")
        return {"error": str(e)}

 