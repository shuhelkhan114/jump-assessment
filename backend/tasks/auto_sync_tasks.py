"""
Auto-sync tasks for periodic data synchronization
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List
import structlog
from celery_app import celery_app
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from tasks.gmail_tasks import sync_gmail_emails, sync_all_users_gmail
from tasks.hubspot_tasks import sync_hubspot_contacts, sync_hubspot_deals, sync_hubspot_companies, sync_all_users_hubspot
from database import User
from config import get_settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import os

logger = structlog.get_logger()
settings = get_settings()

# Create synchronous database engine for Celery tasks
sync_engine = create_engine(settings.database_url, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine)

@celery_app.task(bind=True, max_retries=3)
def auto_sync_all_users(self):
    """
    Periodic task to sync data for all users every 5 minutes
    """
    try:
        logger.info("🔄 Starting auto-sync for all users")
        
        # Get all users who have connected their accounts
        with SyncSessionLocal() as session:
            # Query for users who have Google or HubSpot tokens
            result = session.execute(
                select(User).where(
                    (User.google_access_token.is_not(None)) |
                    (User.hubspot_access_token.is_not(None))
                )
            )
            users = result.scalars().all()
            
            if not users:
                logger.info("No users with connected accounts found")
                return {
                    "users_processed": 0,
                    "gmail_synced": 0,
                    "hubspot_contacts_synced": 0,
                    "hubspot_deals_synced": 0,
                    "hubspot_companies_synced": 0,
                    "errors": []
                }
            
            logger.info(f"Found {len(users)} users with connected accounts")
            
            # Track results
            gmail_synced = 0
            hubspot_contacts_synced = 0
            hubspot_deals_synced = 0
            hubspot_companies_synced = 0
            errors = []
            
            # Queue sync tasks for each user
            for user in users:
                try:
                    # Sync Gmail if user has Google token
                    if user.google_access_token:
                        gmail_result = sync_gmail_emails.delay(user.id, days_back=7)
                        gmail_synced += 1
                        logger.info(f"📧 Gmail sync queued for user {user.id}")
                    
                    # Sync HubSpot if user has HubSpot token
                    if user.hubspot_access_token:
                        contacts_result = sync_hubspot_contacts.delay(user.id)
                        deals_result = sync_hubspot_deals.delay(user.id)
                        companies_result = sync_hubspot_companies.delay(user.id)
                        hubspot_contacts_synced += 1
                        hubspot_deals_synced += 1
                        hubspot_companies_synced += 1
                        logger.info(f"🔗 HubSpot sync queued for user {user.id}")
                    
                except Exception as user_error:
                    error_msg = f"Failed to queue sync for user {user.id}: {str(user_error)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
            
            result = {
                "users_processed": len(users),
                "gmail_synced": gmail_synced,
                "hubspot_contacts_synced": hubspot_contacts_synced,
                "hubspot_deals_synced": hubspot_deals_synced,
                "hubspot_companies_synced": hubspot_companies_synced,
                "errors": errors
            }
            
            logger.info(f"✅ Auto-sync completed for {len(users)} users: {result}")
            return result
        
    except Exception as exc:
        logger.error(f"❌ Auto-sync failed: {str(exc)}")
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))



@celery_app.task(bind=True, max_retries=3)
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



@celery_app.task(bind=True, max_retries=3)
def initial_gmail_sync(self, user_id: str):
    """
    Task to perform initial Gmail sync when user connects Google OAuth
    """
    try:
        logger.info(f"📧 Starting initial Gmail sync for user {user_id}")
        
        # Queue Gmail sync task with shorter time period to get latest emails first
        gmail_result = sync_gmail_emails.delay(user_id, days_back=7)  # Start with 7 days
        
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



@celery_app.task(bind=True, max_retries=3)
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



@celery_app.task
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



@celery_app.task
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



@celery_app.task
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

@celery_app.task(bind=True)
def sync_all_data(self):
    """Main sync task that triggers all data synchronization"""
    try:
        logger.info("Starting automatic data sync for all users")
        
        # First, proactively refresh any tokens that are about to expire
        refresh_expiring_tokens.delay()
        
        # Then run the actual sync tasks
        sync_all_users_gmail.delay()
        
        # Schedule HubSpot sync for all users  
        sync_all_users_hubspot.delay()
        
        logger.info("Automatic data sync scheduled for all users")
        return {"status": "success", "message": "Data sync scheduled for all users"}
        
    except Exception as e:
        logger.error(f"Failed to schedule automatic data sync: {str(e)}")
        raise self.retry(exc=e, countdown=300, max_retries=3)

@celery_app.task(bind=True)
def refresh_expiring_tokens(self):
    """Proactively refresh Google tokens that are about to expire"""
    try:
        logger.info("Starting proactive token refresh check")
        
        with SyncSessionLocal() as session:
            # Find users with Google tokens that expire within the next 30 minutes
            thirty_minutes_from_now = datetime.now(timezone.utc) + timedelta(minutes=30)
            
            result = session.execute(
                select(User).where(
                    User.google_access_token.isnot(None),
                    User.google_refresh_token.isnot(None),
                    User.google_token_expires_at.isnot(None),
                    User.google_token_expires_at <= thirty_minutes_from_now
                )
            )
            users_to_refresh = result.scalars().all()
            
            refreshed_count = 0
            failed_count = 0
            
            for user in users_to_refresh:
                try:
                    logger.info(f"Proactively refreshing Google token for user {user.id}")
                    
                    # Create credentials object
                    credentials = Credentials(
                        token=user.google_access_token,
                        refresh_token=user.google_refresh_token,
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.getenv("GOOGLE_CLIENT_ID"),
                        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
                        scopes=[
                            "https://www.googleapis.com/auth/gmail.readonly",
                            "https://www.googleapis.com/auth/gmail.modify",
                            "https://www.googleapis.com/auth/gmail.compose",
                            "https://www.googleapis.com/auth/calendar"
                        ]
                    )
                    
                    # Refresh the token
                    old_token = credentials.token
                    credentials.refresh(Request())
                    
                    # Update database with new tokens
                    if credentials.token != old_token:
                        user.google_access_token = credentials.token
                        if credentials.refresh_token:  # Update refresh token if provided
                            user.google_refresh_token = credentials.refresh_token
                        user.google_token_expires_at = credentials.expiry
                        user.updated_at = datetime.utcnow()
                        
                        session.commit()
                        refreshed_count += 1
                        logger.info(f"Successfully refreshed Google token for user {user.id}")
                    else:
                        logger.warning(f"Token refresh for user {user.id} didn't return a new token")
                    
                except Exception as user_error:
                    failed_count += 1
                    logger.error(f"Failed to refresh Google token for user {user.id}: {str(user_error)}")
                    # Continue with other users
                    continue
            
            logger.info(f"Proactive token refresh completed: {refreshed_count} refreshed, {failed_count} failed")
            return {
                "status": "success",
                "refreshed_count": refreshed_count,
                "failed_count": failed_count,
                "total_checked": len(users_to_refresh)
            }
        
    except Exception as e:
        logger.error(f"Proactive token refresh failed: {str(e)}")
        raise self.retry(exc=e, countdown=300, max_retries=3)

 