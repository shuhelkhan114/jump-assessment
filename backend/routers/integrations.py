from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import structlog
from datetime import datetime

from auth import get_current_user, require_google_auth, require_hubspot_auth
from database import AsyncSessionLocal, Email, HubspotContact, HubspotDeal, HubspotCompany, select

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

@router.get("/status")
async def get_integration_status(current_user: dict = Depends(get_current_user)):
    """Get integration connection status"""
    try:
        return {
            "google": bool(current_user.get("google_access_token")),
            "hubspot": bool(current_user.get("hubspot_access_token"))
        }
        
    except Exception as e:
        logger.error(f"Failed to get integration status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get integration status"
        )

@router.get("/hubspot/auth-url")
async def get_hubspot_auth_url(current_user: dict = Depends(get_current_user)):
    """Get HubSpot OAuth authorization URL"""
    try:
        from config import get_settings
        import secrets
        
        settings = get_settings()
        
        if not settings.hubspot_client_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="HubSpot OAuth not configured"
            )
        
        # Import the oauth_states from auth module to share state storage
        try:
            from routers.auth import oauth_states
        except ImportError:
            # Fallback if not available
            oauth_states = {}
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        oauth_states[state] = {"provider": "hubspot", "user_id": current_user["id"]}
        
        # HubSpot OAuth parameters
        from urllib.parse import urlencode
        params = {
            "client_id": settings.hubspot_client_id,
            "redirect_uri": settings.hubspot_redirect_uri,
            "scope": "oauth crm.objects.owners.read",
            "optional_scope": "crm.objects.contacts.read crm.objects.contacts.write crm.objects.companies.read crm.objects.deals.read",
            "state": state
        }
        
        auth_url = f"https://app.hubspot.com/oauth/authorize?{urlencode(params)}"
        
        return {"auth_url": auth_url}
        
    except Exception as e:
        logger.error(f"Failed to get HubSpot auth URL: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get HubSpot auth URL"
        )

@router.post("/gmail/sync")
async def sync_gmail(
    days_back: int = 30,
    current_user: dict = Depends(require_google_auth)
):
    """Sync Gmail data"""
    try:
        # Import Gmail tasks
        from tasks.gmail_tasks import sync_gmail_emails
        
        # Use Celery for background processing
        task = sync_gmail_emails.delay(current_user["id"], days_back)
        
        return {
            "message": "Gmail sync started",
            "task_id": task.id,
            "days_back": days_back
        }
        
    except Exception as e:
        logger.error(f"Failed to start Gmail sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start Gmail sync"
        )

@router.get("/gmail/task-status/{task_id}")
async def get_gmail_task_status(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Check Gmail sync task status"""
    try:
        from celery.result import AsyncResult
        
        # Get task result
        task_result = AsyncResult(task_id)
        
        return {
            "task_id": task_id,
            "status": task_result.status,
            "result": task_result.result if task_result.ready() else None,
            "info": task_result.info
        }
        
    except Exception as e:
        logger.error(f"Failed to get task status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get task status"
        )

@router.post("/hubspot/sync")
async def sync_hubspot(
    data_type: str = "all",  # "all", "contacts", "deals", "companies"
    current_user: dict = Depends(require_hubspot_auth)
):
    """Sync HubSpot data"""
    try:
        # Import HubSpot tasks
        from tasks.hubspot_tasks import (
            sync_all_hubspot_data, 
            sync_hubspot_contacts, 
            sync_hubspot_deals, 
            sync_hubspot_companies
        )
        
        # Start appropriate sync based on data type
        if data_type == "contacts":
            task = sync_hubspot_contacts.delay(current_user["id"])
        elif data_type == "deals":
            task = sync_hubspot_deals.delay(current_user["id"])
        elif data_type == "companies":
            task = sync_hubspot_companies.delay(current_user["id"])
        else:  # "all" or default
            task = sync_all_hubspot_data.delay(current_user["id"])
        
        return {
            "message": f"HubSpot {data_type} sync started",
            "task_id": task.id,
            "data_type": data_type
        }
        
    except Exception as e:
        logger.error(f"Failed to start HubSpot sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start HubSpot sync"
        )

@router.get("/hubspot/task-status/{task_id}")
async def get_hubspot_task_status(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Check HubSpot sync task status"""
    try:
        from celery.result import AsyncResult
        
        # Get task result
        task_result = AsyncResult(task_id)
        
        return {
            "task_id": task_id,
            "status": task_result.status,
            "result": task_result.result if task_result.ready() else None,
            "info": task_result.info
        }
        
    except Exception as e:
        logger.error(f"Failed to get HubSpot task status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get HubSpot task status"
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
                      Email.received_at, Email.is_read, Email.content)
                .where(Email.user_id == current_user["id"])
                .order_by(Email.received_at.desc())
                .limit(limit)
            )
            emails = result.all()
            
            return [
                {
                    "id": email.id,
                    "subject": email.subject,
                    "sender": email.sender,
                    "recipient": email.recipient,
                    "received_at": email.received_at,
                    "is_read": email.is_read,
                    "content": email.content[:200] + "..." if len(email.content or "") > 200 else email.content
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
                select(HubspotContact.id, HubspotContact.firstname, HubspotContact.lastname,
                      HubspotContact.email, HubspotContact.phone, HubspotContact.company, 
                      HubspotContact.jobtitle, HubspotContact.industry, HubspotContact.lifecyclestage)
                .where(HubspotContact.user_id == current_user["id"])
                .order_by(HubspotContact.created_at.desc())
                .limit(limit)
            )
            contacts = result.all()
            
            return [
                {
                    "id": contact.id,
                    "name": f"{contact.firstname or ''} {contact.lastname or ''}".strip() or "Unknown",
                    "email": contact.email,
                    "phone": contact.phone,
                    "company": contact.company,
                    "jobtitle": contact.jobtitle,
                    "industry": contact.industry,
                    "lifecyclestage": contact.lifecyclestage
                }
                for contact in contacts
            ]
        
    except Exception as e:
        logger.error(f"Failed to fetch contacts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch contacts"
        )

@router.get("/hubspot/deals")
async def get_deals(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get HubSpot deals"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(HubspotDeal.id, HubspotDeal.dealname, HubspotDeal.amount,
                      HubspotDeal.dealstage, HubspotDeal.pipeline, HubspotDeal.closedate,
                      HubspotDeal.description)
                .where(HubspotDeal.user_id == current_user["id"])
                .order_by(HubspotDeal.created_at.desc())
                .limit(limit)
            )
            deals = result.all()
            
            return [
                {
                    "id": deal.id,
                    "dealname": deal.dealname,
                    "amount": deal.amount,
                    "dealstage": deal.dealstage,
                    "pipeline": deal.pipeline,
                    "closedate": deal.closedate.isoformat() if deal.closedate else None,
                    "description": deal.description
                }
                for deal in deals
            ]
        
    except Exception as e:
        logger.error(f"Failed to fetch deals: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch deals"
        )

@router.get("/hubspot/companies")
async def get_companies(
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """Get HubSpot companies"""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(HubspotCompany.id, HubspotCompany.name, HubspotCompany.domain,
                      HubspotCompany.industry, HubspotCompany.city, HubspotCompany.state,
                      HubspotCompany.num_employees, HubspotCompany.annualrevenue,
                      HubspotCompany.description)
                .where(HubspotCompany.user_id == current_user["id"])
                .order_by(HubspotCompany.created_at.desc())
                .limit(limit)
            )
            companies = result.all()
            
            return [
                {
                    "id": company.id,
                    "name": company.name,
                    "domain": company.domain,
                    "industry": company.industry,
                    "location": f"{company.city or ''}, {company.state or ''}".strip(', '),
                    "num_employees": company.num_employees,
                    "annualrevenue": company.annualrevenue,
                    "description": company.description
                }
                for company in companies
            ]
        
    except Exception as e:
        logger.error(f"Failed to fetch companies: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch companies"
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

@router.post("/sync")
async def manual_sync(current_user: dict = Depends(get_current_user)):
    """Manual sync for all connected integrations"""
    try:
        sync_results = []
        
        # Check if user has Google OAuth and sync Gmail
        if current_user.get("google_access_token"):
            try:
                from tasks.gmail_tasks import sync_gmail_emails
                gmail_task = sync_gmail_emails.delay(current_user["id"], days_back=7)
                sync_results.append({
                    "service": "gmail",
                    "status": "started",
                    "task_id": gmail_task.id
                })
                logger.info(f"Manual Gmail sync started for user {current_user['id']}")
            except Exception as e:
                logger.error(f"Failed to start Gmail sync: {str(e)}")
                sync_results.append({
                    "service": "gmail",
                    "status": "error",
                    "error": str(e)
                })
        
        # Check if user has HubSpot OAuth and sync HubSpot data
        if current_user.get("hubspot_access_token"):
            try:
                from tasks.hubspot_tasks import sync_all_hubspot_data
                hubspot_task = sync_all_hubspot_data.delay(current_user["id"])
                sync_results.append({
                    "service": "hubspot",
                    "status": "started",
                    "task_id": hubspot_task.id
                })
                logger.info(f"Manual HubSpot sync started for user {current_user['id']}")
            except Exception as e:
                logger.error(f"Failed to start HubSpot sync: {str(e)}")
                sync_results.append({
                    "service": "hubspot",
                    "status": "error",
                    "error": str(e)
                })
        
        if not sync_results:
            return {
                "message": "No connected integrations to sync",
                "sync_results": []
            }
        
        return {
            "message": "Manual sync started for connected integrations",
            "sync_results": sync_results
        }
        
    except Exception as e:
        logger.error(f"Failed to start manual sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start manual sync"
        ) 