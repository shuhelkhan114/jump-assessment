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
from tasks.calendar_tasks import sync_calendar_events
from services.sync_manager import sync_manager
from database import User
from config import get_settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import os
import requests

logger = structlog.get_logger()
settings = get_settings()

# Create synchronous database engine for Celery tasks
sync_engine = create_engine(settings.database_url, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine)

@celery_app.task(bind=True, max_retries=3)
def auto_sync_all_users(self):
    """
    Periodic task to sync all users' data from Gmail and HubSpot
    Runs every 30 minutes via Celery Beat scheduler
    """
    try:
        logger.info("🚀 Starting auto-sync for all users")
        
        with SyncSessionLocal() as session:
            # Get all users with OAuth tokens
            result = session.execute(
                select(User).where(
                    (User.google_access_token.is_not(None)) | 
                    (User.hubspot_access_token.is_not(None))
                )
            )
            users = result.scalars().all()
            
            if not users:
                logger.info("📭 No users with OAuth tokens found")
                return {
                    "users_processed": 0,
                    "gmail_synced": 0,
                    "hubspot_contacts_synced": 0,
                    "hubspot_deals_synced": 0,
                    "hubspot_companies_synced": 0,
                    "thank_you_emails_sent": 0,
                    "errors": []
                }
            
            gmail_synced = 0
            hubspot_contacts_synced = 0
            hubspot_deals_synced = 0
            hubspot_companies_synced = 0
            thank_you_emails_queued = 0
            errors = []
            
            # Queue sync tasks for each user
            for user in users:
                try:
                    # Sync Gmail and Calendar if user has Google token
                    if user.google_access_token:
                        gmail_result = sync_gmail_emails.delay(user.id, days_back=7)
                        calendar_result = sync_calendar_events.delay(user.id, days_forward=30)
                        gmail_synced += 1
                        logger.info(f"📧 Gmail and 📅 Calendar sync queued for user {user.id}")
                    
                    # Sync HubSpot if user has HubSpot token
                    if user.hubspot_access_token:
                        contacts_result = sync_hubspot_contacts.delay(user.id)
                        deals_result = sync_hubspot_deals.delay(user.id)
                        companies_result = sync_hubspot_companies.delay(user.id)
                        hubspot_contacts_synced += 1
                        hubspot_deals_synced += 1
                        hubspot_companies_synced += 1
                        logger.info(f"🔗 HubSpot sync queued for user {user.id}")
                    
                    # Send thank you emails to new HubSpot contacts (if user has both integrations)
                    if user.hubspot_access_token and user.google_access_token:
                        from tasks.hubspot_tasks import send_thank_you_emails_to_new_contacts
                        thank_you_result = send_thank_you_emails_to_new_contacts.delay(user.id)
                        thank_you_emails_queued += 1
                        logger.info(f"💌 Thank you email check queued for user {user.id}")
                    
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
                "thank_you_emails_queued": thank_you_emails_queued,
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
        
        # Queue Gmail and Calendar sync tasks
        gmail_result = sync_gmail_emails.delay(user_id, days_back=7)  # Start with 7 days
        calendar_result = sync_calendar_events.delay(user_id, days_forward=30)  # Next 30 days
        
        result = {
            "user_id": user_id,
            "gmail_synced": True,
            "calendar_synced": True,
            "gmail_task_id": gmail_result.id,
            "calendar_task_id": calendar_result.id
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
def refresh_expiring_tokens(self):
    """Proactively refresh Google and HubSpot tokens that are about to expire"""
    try:
        logger.info("Starting proactive token refresh check for all services")
        
        with SyncSessionLocal() as session:
            # Find users with tokens that expire within the next 30 minutes
            thirty_minutes_from_now = datetime.now(timezone.utc) + timedelta(minutes=30)
            
            # Get users with Google tokens that need refresh
            google_result = session.execute(
                select(User).where(
                    User.google_access_token.isnot(None),
                    User.google_refresh_token.isnot(None),
                    User.google_token_expires_at.isnot(None),
                    User.google_token_expires_at <= thirty_minutes_from_now
                )
            )
            google_users = google_result.scalars().all()
            
            # Get users with HubSpot tokens that need refresh
            hubspot_result = session.execute(
                select(User).where(
                    User.hubspot_access_token.isnot(None),
                    User.hubspot_refresh_token.isnot(None),
                    User.hubspot_token_expires_at.isnot(None),
                    User.hubspot_token_expires_at <= thirty_minutes_from_now
                )
            )
            hubspot_users = hubspot_result.scalars().all()
            
            google_refreshed = 0
            google_failed = 0
            hubspot_refreshed = 0
            hubspot_failed = 0
            
            # Refresh Google tokens
            for user in google_users:
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
                        google_refreshed += 1
                        logger.info(f"Successfully refreshed Google token for user {user.id}")
                    else:
                        logger.warning(f"Google token refresh for user {user.id} didn't return a new token")
                    
                except Exception as user_error:
                    google_failed += 1
                    logger.error(f"Failed to refresh Google token for user {user.id}: {str(user_error)}")
                    # Continue with other users
                    continue
            
            # Refresh HubSpot tokens
            for user in hubspot_users:
                try:
                    logger.info(f"Proactively refreshing HubSpot token for user {user.id}")
                    
                    import requests
                    # Refresh HubSpot token using OAuth2 refresh flow
                    response = requests.post(
                        "https://api.hubapi.com/oauth/v1/token",
                        data={
                            "grant_type": "refresh_token",
                            "client_id": os.getenv("HUBSPOT_CLIENT_ID"),
                            "client_secret": os.getenv("HUBSPOT_CLIENT_SECRET"),
                            "refresh_token": user.hubspot_refresh_token
                        },
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        token_data = response.json()
                        
                        # Update user tokens
                        user.hubspot_access_token = token_data["access_token"]
                        expires_in = token_data.get("expires_in", 21600)  # Default 6 hours
                        user.hubspot_token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                        
                        # Update refresh token if provided
                        if "refresh_token" in token_data:
                            user.hubspot_refresh_token = token_data["refresh_token"]
                        
                        user.updated_at = datetime.utcnow()
                        session.commit()
                        hubspot_refreshed += 1
                        logger.info(f"Successfully refreshed HubSpot token for user {user.id}")
                    else:
                        hubspot_failed += 1
                        logger.error(f"Failed to refresh HubSpot token for user {user.id}: HTTP {response.status_code} - {response.text}")
                    
                except Exception as user_error:
                    hubspot_failed += 1
                    logger.error(f"Failed to refresh HubSpot token for user {user.id}: {str(user_error)}")
                    # Continue with other users
                    continue
            
            logger.info(f"Token refresh completed - Google: {google_refreshed} refreshed, {google_failed} failed | HubSpot: {hubspot_refreshed} refreshed, {hubspot_failed} failed")
            return {
                "status": "success",
                "google": {
                    "refreshed_count": google_refreshed,
                    "failed_count": google_failed,
                    "total_checked": len(google_users)
                },
                "hubspot": {
                    "refreshed_count": hubspot_refreshed,
                    "failed_count": hubspot_failed,
                    "total_checked": len(hubspot_users)
                }
            }
        
    except Exception as e:
        logger.error(f"Proactive token refresh failed: {str(e)}")
        raise self.retry(exc=e, countdown=300, max_retries=3)

@celery_app.task(bind=True)
def robust_sync_all_users(self):
    """
    Robust periodic task using the unified sync manager
    Replaces auto_sync_all_users with better error handling and token management
    """
    try:
        logger.info("🔄 Starting robust auto-sync for all users")
        
        # Get all users who have connected their accounts
        with SyncSessionLocal() as session:
            result = session.execute(
                select(User).where(
                    (User.google_access_token.is_not(None)) |
                    (User.hubspot_access_token.is_not(None))
                )
            )
            users = result.scalars().all()
            
            if not users:
                logger.info("No users with connected accounts found")
                return {"users_processed": 0, "errors": []}
            
            logger.info(f"Found {len(users)} users with connected accounts")
            
            results = {
                "users_processed": len(users),
                "successful_users": 0,
                "failed_users": 0,
                "sync_results": {},
                "errors": []
            }
            
            # Process each user with the sync manager
            for user in users:
                try:
                    # Use the sync manager for robust sync
                    user_results = asyncio.run(sync_manager.sync_all_data(user.id))
                    
                    # Check if sync was successful
                    success_count = sum(1 for r in user_results.values() 
                                      if hasattr(r, 'status') and r.status.value == "success")
                    total_count = len(user_results)
                    
                    if success_count > 0:
                        results["successful_users"] += 1
                        logger.info(f"✅ User {user.id}: {success_count}/{total_count} services synced")
                    else:
                        results["failed_users"] += 1
                        logger.warning(f"⚠️ User {user.id}: no services synced successfully")
                    
                    # Store results for detailed reporting
                    results["sync_results"][user.id] = {
                        "success_count": success_count,
                        "total_count": total_count,
                        "services": {
                            service: {
                                "status": r.status.value if hasattr(r, 'status') else str(r),
                                "message": r.message if hasattr(r, 'message') else str(r)
                            }
                            for service, r in user_results.items()
                        }
                    }
                    
                except Exception as user_error:
                    results["failed_users"] += 1
                    error_msg = f"Failed to sync user {user.id}: {str(user_error)}"
                    results["errors"].append(error_msg)
                    logger.error(error_msg)
            
            logger.info(f"✅ Robust auto-sync completed: {results['successful_users']} successful, {results['failed_users']} failed")
            return results
        
    except Exception as exc:
        logger.error(f"❌ Robust auto-sync failed: {str(exc)}")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery_app.task(bind=True, max_retries=3)
def robust_initial_sync(self, user_id: str, force_refresh: bool = False):
    """
    Robust initial sync using the unified sync manager
    """
    try:
        logger.info(f"🚀 Starting robust initial sync for user {user_id}")
        
        # Use the sync manager for comprehensive sync
        sync_results = asyncio.run(sync_manager.sync_all_data(user_id, force_refresh=force_refresh))
        
        # Process results
        successful_services = []
        failed_services = []
        
        for service, result in sync_results.items():
            if hasattr(result, 'status'):
                if result.status.value == "success":
                    successful_services.append(service)
                else:
                    failed_services.append(f"{service}: {result.message}")
            else:
                failed_services.append(f"{service}: {str(result)}")
        
        overall_success = len(successful_services) > len(failed_services)
        
        result_data = {
            "user_id": user_id,
            "overall_success": overall_success,
            "successful_services": successful_services,
            "failed_services": failed_services,
            "sync_results": {
                service: {
                    "status": r.status.value if hasattr(r, 'status') else str(r),
                    "message": r.message if hasattr(r, 'message') else str(r)
                }
                for service, r in sync_results.items()
            }
        }
        
        if overall_success:
            logger.info(f"✅ Robust initial sync completed for user {user_id}: {len(successful_services)} services synced")
        else:
            logger.warning(f"⚠️ Robust initial sync partially failed for user {user_id}: {len(failed_services)} services failed")
        
        return result_data
        
    except Exception as exc:
        logger.error(f"❌ Robust initial sync failed for user {user_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@celery_app.task
def robust_trigger_sync(user_id: str, services: list = None):
    """
    Robust sync trigger that can sync all or specific services
    """
    try:
        logger.info(f"🔄 Triggering robust sync for user {user_id}, services: {services}")
        
        if services:
            # Sync specific services
            results = {}
            for service in services:
                if service == "thank_you_emails":
                    # Handle thank you emails separately
                    from tasks.hubspot_tasks import send_thank_you_emails_to_new_contacts
                    thank_you_result = send_thank_you_emails_to_new_contacts.delay(user_id)
                    results[service] = {
                        "status": "queued",
                        "message": f"Thank you email task queued: {thank_you_result.id}"
                    }
                else:
                    result = asyncio.run(sync_manager.sync_single_service(user_id, service))
                    results[service] = {
                        "status": result.status.value,
                        "message": result.message
                    }
        else:
            # Sync all services
            sync_results = asyncio.run(sync_manager.sync_all_data(user_id))
            results = {
                service: {
                    "status": r.status.value if hasattr(r, 'status') else str(r),
                    "message": r.message if hasattr(r, 'message') else str(r)
                }
                for service, r in sync_results.items()
            }
            
            # Also trigger thank you emails for complete sync
            from tasks.hubspot_tasks import send_thank_you_emails_to_new_contacts
            thank_you_result = send_thank_you_emails_to_new_contacts.delay(user_id)
            results["thank_you_emails"] = {
                "status": "queued",
                "message": f"Thank you email task queued: {thank_you_result.id}"
            }
        
        logger.info(f"✅ Robust sync completed for user {user_id}")
        return {"sync_triggered": True, "results": results}
        
    except Exception as e:
        logger.error(f"❌ Failed to trigger robust sync for user {user_id}: {str(e)}")
        return {"error": str(e)}


@celery_app.task
def health_check_all_users():
    """
    Health check for all users' integrations
    """
    try:
        logger.info("🏥 Running health check for all users")
        
        with SyncSessionLocal() as session:
            result = session.execute(
                select(User).where(
                    (User.google_access_token.is_not(None)) |
                    (User.hubspot_access_token.is_not(None))
                )
            )
            users = result.scalars().all()
            
            health_results = {}
            healthy_users = 0
            degraded_users = 0
            
            for user in users:
                try:
                    health_status = asyncio.run(sync_manager.health_check(user.id))
                    health_results[user.id] = health_status
                    
                    if health_status.get("overall_status") == "healthy":
                        healthy_users += 1
                    else:
                        degraded_users += 1
                        
                except Exception as e:
                    health_results[user.id] = {"status": "error", "message": str(e)}
                    degraded_users += 1
            
            summary = {
                "total_users": len(users),
                "healthy_users": healthy_users,
                "degraded_users": degraded_users,
                "health_results": health_results
            }
            
            logger.info(f"🏥 Health check completed: {healthy_users} healthy, {degraded_users} degraded")
            return summary
            
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}")
        return {"error": str(e)}

 