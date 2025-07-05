from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import structlog
from datetime import datetime

from auth import get_current_user, require_google_auth, require_hubspot_auth
from database import AsyncSessionLocal, Email, HubspotContact, select

logger = structlog.get_logger()

# Import Celery tasks (will be created later)
try:
    from celery_app import celery_app
except ImportError:
    celery_app = None
    logger.warning("Celery not available, falling back to synchronous processing")

router = APIRouter()

# Pydantic models
class SyncStatus(BaseModel):
    service: str
    status: str
    last_sync: Optional[datetime] = None
    total_items: int = 0
    error_message: Optional[str] = None

class EmailSummary(BaseModel):
    total_emails: int
    unread_emails: int
    last_sync: Optional[datetime] = None

class HubSpotSummary(BaseModel):
    total_contacts: int
    last_sync: Optional[datetime] = None

@router.get("/sync-status")
async def get_sync_status(current_user: dict = Depends(get_current_user)):
    """Get sync status for all integrations"""
    try:
        gmail_status = await get_gmail_sync_status(current_user["id"])
        hubspot_status = await get_hubspot_sync_status(current_user["id"])
        
        return {
            "gmail": gmail_status,
            "hubspot": hubspot_status
        }
        
    except Exception as e:
        logger.error(f"Failed to get sync status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get sync status"
        )

@router.post("/gmail/sync")
async def sync_gmail(
    current_user: dict = Depends(require_google_auth)
):
    """Sync Gmail data"""
    try:
        if celery_app:
            # Use Celery for background processing
            task = celery_app.send_task("sync_gmail_data", args=[current_user["id"]])
            return {"message": "Gmail sync started", "task_id": task.id}
        else:
            # Fallback to synchronous processing
            await sync_gmail_data(current_user["id"])
            return {"message": "Gmail sync completed"}
        
    except Exception as e:
        logger.error(f"Failed to start Gmail sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start Gmail sync"
        )

@router.post("/hubspot/sync")
async def sync_hubspot(
    current_user: dict = Depends(require_hubspot_auth)
):
    """Sync HubSpot data"""
    try:
        if celery_app:
            # Use Celery for background processing
            task = celery_app.send_task("sync_hubspot_data", args=[current_user["id"]])
            return {"message": "HubSpot sync started", "task_id": task.id}
        else:
            # Fallback to synchronous processing
            await sync_hubspot_data(current_user["id"])
            return {"message": "HubSpot sync completed"}
        
    except Exception as e:
        logger.error(f"Failed to start HubSpot sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start HubSpot sync"
        )

@router.get("/gmail/emails")
async def get_emails(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get Gmail emails"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Email.id, Email.subject, Email.sender, Email.recipient, 
                      Email.date, Email.is_read, Email.is_sent)
                .where(Email.user_id == current_user["id"])
                .order_by(Email.date.desc())
                .limit(limit)
            )
            emails = result.all()
            
            return [
                {
                    "id": email.id,
                    "subject": email.subject,
                    "sender": email.sender,
                    "recipient": email.recipient,
                    "date": email.date,
                    "is_read": email.is_read,
                    "is_sent": email.is_sent
                }
                for email in emails
            ]
        
    except Exception as e:
        logger.error(f"Failed to fetch emails: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch emails"
        )

@router.get("/hubspot/contacts")
async def get_contacts(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get HubSpot contacts"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(HubspotContact.id, HubspotContact.name, HubspotContact.email, 
                      HubspotContact.phone, HubspotContact.company, HubspotContact.notes)
                .where(HubspotContact.user_id == current_user["id"])
                .order_by(HubspotContact.created_at.desc())
                .limit(limit)
            )
            contacts = result.all()
            
            return [
                {
                    "id": contact.id,
                    "name": contact.name,
                    "email": contact.email,
                    "phone": contact.phone,
                    "company": contact.company,
                    "notes": contact.notes
                }
                for contact in contacts
            ]
        
    except Exception as e:
        logger.error(f"Failed to fetch contacts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch contacts"
        )

@router.get("/gmail/summary", response_model=EmailSummary)
async def get_gmail_summary(current_user: dict = Depends(get_current_user)):
    """Get Gmail summary"""
    try:
        from sqlalchemy import func, case
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    func.count(Email.id).label("total_emails"),
                    func.count(case((Email.is_read == False, 1), else_=None)).label("unread_emails"),
                    func.max(Email.created_at).label("last_sync")
                )
                .where(Email.user_id == current_user["id"])
            )
            summary = result.first()
            
            return EmailSummary(
                total_emails=summary.total_emails or 0,
                unread_emails=summary.unread_emails or 0,
                last_sync=summary.last_sync
            )
        
    except Exception as e:
        logger.error(f"Failed to get Gmail summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get Gmail summary"
        )

@router.get("/hubspot/summary", response_model=HubSpotSummary)
async def get_hubspot_summary(current_user: dict = Depends(get_current_user)):
    """Get HubSpot summary"""
    try:
        from sqlalchemy import func
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    func.count(HubspotContact.id).label("total_contacts"),
                    func.max(HubspotContact.created_at).label("last_sync")
                )
                .where(HubspotContact.user_id == current_user["id"])
            )
            summary = result.first()
            
            return HubSpotSummary(
                total_contacts=summary.total_contacts or 0,
                last_sync=summary.last_sync
            )
        
    except Exception as e:
        logger.error(f"Failed to get HubSpot summary: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get HubSpot summary"
        )

# Background tasks
async def sync_gmail_data(user_id: str):
    """Background task to sync Gmail data"""
    try:
        logger.info(f"Starting Gmail sync for user {user_id}")
        
        # TODO: Implement Gmail API integration
        # For now, just log the task
        logger.info(f"Gmail sync completed for user {user_id}")
        
    except Exception as e:
        logger.error(f"Gmail sync failed for user {user_id}: {str(e)}")

async def sync_hubspot_data(user_id: str):
    """Background task to sync HubSpot data"""
    try:
        logger.info(f"Starting HubSpot sync for user {user_id}")
        
        # TODO: Implement HubSpot API integration
        # For now, just log the task
        logger.info(f"HubSpot sync completed for user {user_id}")
        
    except Exception as e:
        logger.error(f"HubSpot sync failed for user {user_id}: {str(e)}")

# Helper functions
async def get_gmail_sync_status(user_id: str) -> SyncStatus:
    """Get Gmail sync status"""
    try:
        from sqlalchemy import func
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    func.count(Email.id).label("total_emails"),
                    func.max(Email.created_at).label("last_sync")
                )
                .where(Email.user_id == user_id)
            )
            summary = result.first()
            
            return SyncStatus(
                service="gmail",
                status="connected" if summary.total_emails > 0 else "not_synced",
                last_sync=summary.last_sync,
                total_items=summary.total_emails or 0
            )
        
    except Exception as e:
        logger.error(f"Failed to get Gmail sync status: {str(e)}")
        return SyncStatus(
            service="gmail",
            status="error",
            error_message=str(e)
        )

async def get_hubspot_sync_status(user_id: str) -> SyncStatus:
    """Get HubSpot sync status"""
    try:
        from sqlalchemy import func
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(
                    func.count(HubspotContact.id).label("total_contacts"),
                    func.max(HubspotContact.created_at).label("last_sync")
                )
                .where(HubspotContact.user_id == user_id)
            )
            summary = result.first()
            
            return SyncStatus(
                service="hubspot",
                status="connected" if summary.total_contacts > 0 else "not_synced",
                last_sync=summary.last_sync,
                total_items=summary.total_contacts or 0
            )
        
    except Exception as e:
        logger.error(f"Failed to get HubSpot sync status: {str(e)}")
        return SyncStatus(
            service="hubspot",
            status="error",
            error_message=str(e)
        ) 