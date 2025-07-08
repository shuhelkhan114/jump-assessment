from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import structlog
from datetime import datetime, timedelta
import base64
import json
import hmac
import hashlib

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

class RobustSyncResult(BaseModel):
    user_id: str
    overall_success: bool
    successful_services: List[str]
    failed_services: List[str]
    sync_results: Dict[str, Dict[str, str]]

class HealthCheckResult(BaseModel):
    user_id: str
    timestamp: str
    overall_status: str
    services: Dict[str, Dict[str, str]]

class RobustSyncRequest(BaseModel):
    force_refresh: bool = False
    services: Optional[List[str]] = None

class SystemStatusResult(BaseModel):
    timestamp: str
    uptime_seconds: float
    uptime_human: str
    performance_metrics: Dict[str, Any]
    cache_stats: Dict[str, Any]
    database_stats: Dict[str, Any]
    system_health: str

class PerformanceRecommendations(BaseModel):
    timestamp: str
    recommendations: List[str]
    system_health: str
    critical_issues: int
    total_operations: int

# Integration Models

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

@router.post("/hubspot/send-thank-you-emails")
async def send_thank_you_emails(
    current_user: dict = Depends(require_hubspot_auth)
):
    """Manually trigger thank you emails for new HubSpot contacts"""
    try:
        # Import the task
        from tasks.hubspot_tasks import send_thank_you_emails_to_new_contacts
        
        # Start the task
        task = send_thank_you_emails_to_new_contacts.delay(current_user["id"])
        
        return {
            "success": True,
            "message": "Thank you email task started",
            "task_id": task.id,
            "user_id": current_user["id"]
        }
        
    except Exception as e:
        logger.error(f"Failed to trigger thank you emails: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger thank you emails: {str(e)}"
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
        
        # Check if user has Google OAuth and sync Gmail & Calendar
        if current_user.get("google_access_token"):
            try:
                from tasks.gmail_tasks import sync_gmail_emails
                from tasks.calendar_tasks import sync_calendar_events
                
                gmail_task = sync_gmail_emails.delay(current_user["id"], days_back=7)
                calendar_task = sync_calendar_events.delay(current_user["id"], days_forward=30)
                
                sync_results.append({
                    "service": "gmail",
                    "status": "started",
                    "task_id": gmail_task.id
                })
                sync_results.append({
                    "service": "calendar", 
                    "status": "started",
                    "task_id": calendar_task.id
                })
                logger.info(f"Manual Gmail and Calendar sync started for user {current_user['id']}")
            except Exception as e:
                logger.error(f"Failed to start Gmail/Calendar sync: {str(e)}")
                sync_results.append({
                    "service": "gmail",
                    "status": "error",
                    "error": str(e)
                })
                sync_results.append({
                    "service": "calendar",
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

# ROBUST SYNC ENDPOINTS using the Unified Sync Manager

@router.post("/robust-sync")
async def robust_manual_sync(
    request: RobustSyncRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Robust manual sync using the unified sync manager with proactive token refresh
    """
    try:
        from tasks.auto_sync_tasks import robust_trigger_sync
        
        # Trigger robust sync with optional service filtering
        task = robust_trigger_sync.delay(current_user["id"], request.services)
        
        return {
            "message": "Robust sync started",
            "task_id": task.id,
            "force_refresh": request.force_refresh,
            "services": request.services or "all"
        }
        
    except Exception as e:
        logger.error(f"Failed to start robust sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start robust sync: {str(e)}"
        )

@router.get("/robust-sync/task-status/{task_id}")
async def get_robust_sync_status(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get robust sync task status with detailed results"""
    try:
        from celery.result import AsyncResult
        
        task_result = AsyncResult(task_id)
        
        response = {
            "task_id": task_id,
            "status": task_result.status,
            "ready": task_result.ready(),
        }
        
        if task_result.ready():
            result = task_result.result
            if isinstance(result, dict) and "results" in result:
                response["sync_results"] = result["results"]
                response["sync_triggered"] = result.get("sync_triggered", False)
            else:
                response["result"] = result
        else:
            response["info"] = task_result.info
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to get robust sync status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get robust sync status"
        )

@router.get("/health-check", response_model=HealthCheckResult)
async def integration_health_check(current_user: dict = Depends(get_current_user)):
    """
    Comprehensive health check for all integrations with token validation
    """
    try:
        from services.sync_manager import sync_manager
        
        # Run health check using sync manager
        health_status = await sync_manager.health_check(current_user["id"])
        
        return HealthCheckResult(
            user_id=health_status["user_id"],
            timestamp=health_status["timestamp"],
            overall_status=health_status["overall_status"],
            services=health_status["services"]
        )
        
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Health check failed: {str(e)}"
        )

@router.post("/initial-sync")
async def robust_initial_sync(
    force_refresh: bool = True,
    current_user: dict = Depends(get_current_user)
):
    """
    Robust initial sync for new user integrations
    """
    try:
        from tasks.auto_sync_tasks import robust_initial_sync
        
        # Trigger robust initial sync
        task = robust_initial_sync.delay(current_user["id"], force_refresh)
        
        return {
            "message": "Robust initial sync started",
            "task_id": task.id,
            "force_refresh": force_refresh
        }
        
    except Exception as e:
        logger.error(f"Failed to start robust initial sync: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start robust initial sync: {str(e)}"
        )

@router.get("/initial-sync/task-status/{task_id}")
async def get_initial_sync_status(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Get initial sync task status with detailed results"""
    try:
        from celery.result import AsyncResult
        
        task_result = AsyncResult(task_id)
        
        response = {
            "task_id": task_id,
            "status": task_result.status,
            "ready": task_result.ready(),
        }
        
        if task_result.ready():
            result = task_result.result
            if isinstance(result, dict):
                response.update({
                    "overall_success": result.get("overall_success", False),
                    "successful_services": result.get("successful_services", []),
                    "failed_services": result.get("failed_services", []),
                    "sync_results": result.get("sync_results", {})
                })
            else:
                response["result"] = result
        else:
            response["info"] = task_result.info
        
        return response
        
    except Exception as e:
        logger.error(f"Failed to get initial sync status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get initial sync status"
        )

@router.post("/refresh-tokens")
async def refresh_all_tokens(current_user: dict = Depends(get_current_user)):
    """
    Force refresh all tokens for the user
    """
    try:
        from services.token_manager import token_manager
        
        # Refresh all tokens
        results = await token_manager.ensure_valid_tokens(current_user["id"])
        
        return {
            "message": "Token refresh completed",
            "results": results,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Failed to refresh tokens: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh tokens: {str(e)}"
        )

@router.get("/sync-manager-status")
async def get_sync_manager_status(current_user: dict = Depends(get_current_user)):
    """
    Get detailed status from the sync manager
    """
    try:
        from services.sync_manager import sync_manager
        
        # Get last sync status
        status = await sync_manager.get_last_sync_status(current_user["id"])
        
        return status
        
    except Exception as e:
        logger.error(f"Failed to get sync manager status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get sync manager status: {str(e)}"
        )

# MONITORING AND SYSTEM STATUS ENDPOINTS

@router.get("/system-status")
async def get_system_status(current_user: dict = Depends(get_current_user)):
    """
    Get comprehensive system status including performance metrics, cache stats, and database health
    """
    try:
        status = await performance_monitor.get_system_status()
        return SystemStatusResult(**status)
    except Exception as e:
        logger.error(f"Failed to get system status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get system status: {str(e)}")

@router.get("/performance-metrics")
async def get_performance_metrics(current_user: dict = Depends(get_current_user)):
    """
    Get detailed performance metrics for all operations
    """
    try:
        metrics = performance_monitor.metrics.get_metrics_summary()
        return metrics
    except Exception as e:
        logger.error(f"Failed to get performance metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get performance metrics: {str(e)}")

@router.get("/performance-recommendations")
async def get_performance_recommendations(current_user: dict = Depends(get_current_user)):
    """
    Get performance improvement recommendations based on current metrics
    """
    try:
        recommendations = await performance_monitor.get_performance_recommendations()
        metrics = performance_monitor.metrics.get_metrics_summary()
        
        # Count critical issues
        critical_issues = sum(
            1 for op_metrics in metrics['operations'].values()
            if op_metrics['success_rate'] < 90 or op_metrics['avg_time_ms'] > 3000
        )
        
        total_operations = sum(
            op_metrics['count'] for op_metrics in metrics['operations'].values()
        )
        
        return PerformanceRecommendations(
            timestamp=datetime.utcnow().isoformat(),
            recommendations=recommendations,
            system_health=metrics['system_health'],
            critical_issues=critical_issues,
            total_operations=total_operations
        )
    except Exception as e:
        logger.error(f"Failed to get performance recommendations: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get recommendations: {str(e)}")

@router.post("/cleanup-cache")
async def cleanup_cache(current_user: dict = Depends(get_current_user)):
    """
    Manually trigger cache cleanup and optimization
    """
    try:
        # Get stats before cleanup
        before_stats = performance_monitor.cache.get_stats()
        
        # Perform cleanup
        performance_monitor.cleanup()
        
        # Get stats after cleanup
        after_stats = performance_monitor.cache.get_stats()
        
        return {
            "message": "Cache cleanup completed",
            "before": before_stats,
            "after": after_stats,
            "items_cleaned": before_stats['cached_items'] - after_stats['cached_items']
        }
    except Exception as e:
        logger.error(f"Failed to cleanup cache: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to cleanup cache: {str(e)}")

@router.get("/service-diagnostics/{service}")
async def get_service_diagnostics(
    service: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get detailed diagnostics for a specific service
    """
    try:
        user_id = current_user["id"]
        
        if service not in ["gmail", "hubspot", "calendar"]:
            raise HTTPException(status_code=400, detail="Invalid service. Must be gmail, hubspot, or calendar")
        
        # Import service diagnostics
        from services.service_diagnostics import service_diagnostics
        
        if service == "gmail":
            issues = await service_diagnostics.diagnose_gmail_error("", user_id)
        elif service == "hubspot":
            issues = await service_diagnostics.diagnose_hubspot_error("", user_id)
        elif service == "calendar":
            issues = await service_diagnostics.diagnose_calendar_error("", user_id)
        
        # Get service recommendations
        recommendations = await service_diagnostics.get_service_recommendations(user_id)
        
        return {
            "service": service,
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "issues": service_diagnostics.format_issues_for_ui(issues),
            "recommendations": recommendations.get(service, []),
            "total_issues": len(issues)
        }
    except Exception as e:
        logger.error(f"Failed to get {service} diagnostics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get {service} diagnostics: {str(e)}")

@router.get("/user-sync-history")
async def get_user_sync_history(current_user: dict = Depends(get_current_user)):
    """
    Get sync history and statistics for the current user
    """
    try:
        user_id = current_user["id"]
        
        # Get sync stats from performance monitor
        sync_stats = performance_monitor.metrics.sync_stats.get(user_id, {})
        
        # Get general user info
        user_info = await sync_manager._get_user_integrations(user_id)
        
        return {
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "integrations": user_info,
            "sync_statistics": {
                "gmail_syncs": sync_stats.get("gmail_syncs", 0),
                "calendar_syncs": sync_stats.get("calendar_syncs", 0),
                "hubspot_syncs": sync_stats.get("hubspot_syncs", 0),
                "total_syncs": sync_stats.get("total_syncs", 0),
                "failed_syncs": sync_stats.get("failed_syncs", 0),
                "success_rate": round(
                    ((sync_stats.get("total_syncs", 0) - sync_stats.get("failed_syncs", 0)) / 
                     max(sync_stats.get("total_syncs", 1), 1)) * 100, 2
                ),
                "avg_sync_time_seconds": round(sync_stats.get("avg_sync_time", 0), 2),
                "last_sync": sync_stats.get("last_sync")
            }
        }
    except Exception as e:
        logger.error(f"Failed to get user sync history: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get sync history: {str(e)}")

@router.get("/system-summary")
async def get_system_summary(current_user: dict = Depends(get_current_user)):
    """
    Get a comprehensive system summary for dashboard display
    """
    try:
        user_id = current_user["id"]
        
        # Get health check
        health_check = await sync_manager.health_check(user_id)
        
        # Get performance metrics
        performance_metrics = performance_monitor.metrics.get_metrics_summary()
        
        # Get cache stats
        cache_stats = performance_monitor.cache.get_stats()
        
        # Get sync statistics
        sync_stats = performance_monitor.metrics.sync_stats.get(user_id, {})
        
        # Get database stats
        db_stats = await performance_monitor.get_database_stats()
        
        # Get recommendations
        recommendations = await performance_monitor.get_performance_recommendations()
        
        # Calculate overall system score (0-100)
        score_factors = []
        
        # Health factor (40% weight)
        if health_check["overall_status"] == "healthy":
            health_score = 100
        elif health_check["overall_status"] == "warning":
            health_score = 70
        elif health_check["overall_status"] == "degraded":
            health_score = 40
        else:
            health_score = 10
        
        score_factors.append(("health", health_score, 0.4))
        
        # Performance factor (30% weight)
        if performance_metrics["system_health"] == "healthy":
            perf_score = 100
        elif performance_metrics["system_health"] == "warning":
            perf_score = 70
        else:
            perf_score = 30
        
        score_factors.append(("performance", perf_score, 0.3))
        
        # Cache efficiency factor (20% weight)
        cache_score = min(100, cache_stats["hit_rate"] + 20)  # Bonus for having cache
        score_factors.append(("cache", cache_score, 0.2))
        
        # Sync success factor (10% weight)
        total_syncs = sync_stats.get("total_syncs", 0)
        failed_syncs = sync_stats.get("failed_syncs", 0)
        if total_syncs > 0:
            sync_success_rate = ((total_syncs - failed_syncs) / total_syncs) * 100
        else:
            sync_success_rate = 100  # No syncs yet, assume healthy
        
        score_factors.append(("sync", sync_success_rate, 0.1))
        
        # Calculate weighted score
        overall_score = sum(score * weight for _, score, weight in score_factors)
        overall_score = max(0, min(100, round(overall_score)))
        
        # Determine status emoji and message
        if overall_score >= 90:
            status_emoji = "🟢"
            status_message = "Excellent"
        elif overall_score >= 75:
            status_emoji = "🟡"
            status_message = "Good"
        elif overall_score >= 50:
            status_emoji = "🟠"
            status_message = "Needs Attention"
        else:
            status_emoji = "🔴"
            status_message = "Critical Issues"
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
            "overall_score": overall_score,
            "status_emoji": status_emoji,
            "status_message": status_message,
            "health_check": health_check,
            "performance": {
                "system_health": performance_metrics["system_health"],
                "operations_count": sum(op["count"] for op in performance_metrics["operations"].values()),
                "avg_response_time": sum(op["avg_time_ms"] for op in performance_metrics["operations"].values()) / 
                                   max(len(performance_metrics["operations"]), 1),
                "cache_hit_rate": cache_stats["hit_rate"]
            },
            "sync_stats": {
                "total_syncs": sync_stats.get("total_syncs", 0),
                "success_rate": round(sync_success_rate, 1),
                "last_sync": sync_stats.get("last_sync"),
                "avg_sync_time": round(sync_stats.get("avg_sync_time", 0), 2)
            },
            "database": {
                "total_users": db_stats.get("user_stats", {}).get("total_users", 0),
                "google_connected": db_stats.get("user_stats", {}).get("google_connected", 0),
                "hubspot_connected": db_stats.get("user_stats", {}).get("hubspot_connected", 0),
                "total_emails": db_stats.get("table_sizes", {}).get("emails", 0),
                "total_contacts": db_stats.get("table_sizes", {}).get("hubspot_contacts", 0),
                "total_events": db_stats.get("table_sizes", {}).get("calendar_events", 0)
            },
            "recommendations": recommendations[:5],  # Top 5 recommendations
            "score_breakdown": {
                factor: {"score": score, "weight": weight}
                for factor, score, weight in score_factors
            }
        }
    except Exception as e:
        logger.error(f"Failed to get system summary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get system summary: {str(e)}") 

@router.post("/gmail/polling/start")
async def start_gmail_polling(current_user: dict = Depends(get_current_user)):
    """Start Gmail polling service"""
    try:
        from tasks.gmail_polling_tasks import start_gmail_polling
        
        # Start the polling service as a background task
        task = start_gmail_polling.delay()
        
        return {
            "message": "Gmail polling service started",
            "task_id": task.id,
            "polling_interval": "10 seconds"
        }
        
    except Exception as e:
        logger.error(f"Failed to start Gmail polling: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start Gmail polling"
        )

@router.post("/gmail/polling/stop")
async def stop_gmail_polling(current_user: dict = Depends(get_current_user)):
    """Stop Gmail polling service"""
    try:
        from tasks.gmail_polling_tasks import stop_gmail_polling
        
        # Stop the polling service as a background task
        task = stop_gmail_polling.delay()
        
        return {
            "message": "Gmail polling service stopped",
            "task_id": task.id
        }
        
    except Exception as e:
        logger.error(f"Failed to stop Gmail polling: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stop Gmail polling"
        )

@router.get("/gmail/polling/status")
async def get_gmail_polling_status(current_user: dict = Depends(get_current_user)):
    """Get Gmail polling service status"""
    try:
        from tasks.gmail_polling_tasks import check_gmail_polling_status
        
        # Check the polling service status
        task = check_gmail_polling_status.delay()
        
        return {
            "message": "Gmail polling status checked",
            "task_id": task.id
        }
        
    except Exception as e:
        logger.error(f"Failed to check Gmail polling status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check Gmail polling status"
        ) 