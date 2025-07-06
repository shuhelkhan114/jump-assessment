import structlog
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import asyncio
from sqlalchemy import select, update
from database import AsyncSessionLocal, User
from services.token_manager import token_manager
from services.service_diagnostics import service_diagnostics
from services.performance_monitor import performance_monitor
from tasks.gmail_tasks import sync_gmail_emails
from tasks.calendar_tasks import sync_calendar_events
from tasks.hubspot_tasks import sync_hubspot_contacts

logger = structlog.get_logger()

class SyncStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    SKIPPED = "skipped"

class SyncResult:
    def __init__(self, service: str, status: SyncStatus, message: str, data: Dict = None):
        self.service = service
        self.status = status
        self.message = message
        self.data = data or {}
        self.timestamp = datetime.utcnow()

class SyncManager:
    """Centralized sync management for all integrations"""
    
    def __init__(self):
        self.max_retries = 3
        self.retry_delay = 2  # seconds
        
    async def sync_all_data(self, user_id: str, force_refresh: bool = False) -> Dict[str, SyncResult]:
        """
        Sync all available data sources for a user
        Returns dict with service: SyncResult
        """
        logger.info(f"Starting comprehensive sync for user {user_id} (force_refresh={force_refresh})")
        
        # Get user and check available integrations
        user_info = await self._get_user_integrations(user_id)
        if not user_info:
            return {"error": SyncResult("general", SyncStatus.FAILED, "User not found")}
        
        results = {}
        
        # Sync services in parallel for efficiency
        sync_tasks = []
        
        if user_info.get("has_google"):
            sync_tasks.append(self._sync_gmail_safe(user_id, force_refresh))
            sync_tasks.append(self._sync_calendar_safe(user_id, force_refresh))
        
        if user_info.get("has_hubspot"):
            sync_tasks.append(self._sync_hubspot_safe(user_id, force_refresh))
        
        if not sync_tasks:
            logger.warning(f"No integrations available for user {user_id}")
            return {"general": SyncResult("general", SyncStatus.SKIPPED, "No integrations configured")}
        
        # Execute all sync tasks in parallel
        sync_results = await asyncio.gather(*sync_tasks, return_exceptions=True)
        
        # Process results
        service_names = []
        if user_info.get("has_google"):
            service_names.extend(["gmail", "calendar"])
        if user_info.get("has_hubspot"):
            service_names.append("hubspot")
        
        for i, result in enumerate(sync_results):
            service = service_names[i]
            if isinstance(result, Exception):
                results[service] = SyncResult(service, SyncStatus.FAILED, f"Exception: {str(result)}")
            else:
                results[service] = result
        
        # Log overall sync summary
        self._log_sync_summary(user_id, results)
        
        return results
    
    async def sync_single_service(self, user_id: str, service: str, force_refresh: bool = False) -> SyncResult:
        """
        Sync a single service for a user
        """
        logger.info(f"Starting {service} sync for user {user_id}")
        
        if service == "gmail":
            return await self._sync_gmail_safe(user_id, force_refresh)
        elif service == "calendar":
            return await self._sync_calendar_safe(user_id, force_refresh)
        elif service == "hubspot":
            return await self._sync_hubspot_safe(user_id, force_refresh)
        else:
            return SyncResult(service, SyncStatus.FAILED, f"Unknown service: {service}")
    
    async def _sync_gmail_safe(self, user_id: str, force_refresh: bool = False) -> SyncResult:
        """Gmail sync with comprehensive error handling"""
        try:
            # Ensure tokens are valid
            token_result = await token_manager.refresh_google_tokens_if_needed(user_id, force_refresh)
            if not token_result:
                return SyncResult("gmail", SyncStatus.FAILED, "Failed to refresh Google tokens")
            
            # Execute Gmail sync with retry logic
            result = await token_manager.with_retry_and_refresh(
                user_id=user_id,
                operation=self._execute_gmail_sync,
                service="google",
                max_retries=self.max_retries
            )
            
            return SyncResult("gmail", SyncStatus.SUCCESS, "Gmail sync completed successfully", result)
            
        except Exception as e:
            logger.error(f"Gmail sync failed for user {user_id}: {str(e)}")
            
            # Diagnose the error for better user feedback
            try:
                issues = await service_diagnostics.diagnose_gmail_error(str(e), user_id)
                if issues:
                    primary_issue = issues[0]  # Use the first/most critical issue
                    return SyncResult("gmail", SyncStatus.FAILED, primary_issue.message, {
                        "error_code": primary_issue.error_code,
                        "suggestion": primary_issue.suggestion,
                        "recoverable": primary_issue.recoverable,
                        "diagnostics": service_diagnostics.format_issues_for_ui(issues)
                    })
            except Exception as diag_error:
                logger.error(f"Failed to diagnose Gmail error: {str(diag_error)}")
            
            return SyncResult("gmail", SyncStatus.FAILED, f"Gmail sync error: {str(e)}")
    
    async def _sync_calendar_safe(self, user_id: str, force_refresh: bool = False) -> SyncResult:
        """Calendar sync with comprehensive error handling"""
        try:
            # Ensure tokens are valid
            token_result = await token_manager.refresh_google_tokens_if_needed(user_id, force_refresh)
            if not token_result:
                return SyncResult("calendar", SyncStatus.FAILED, "Failed to refresh Google tokens")
            
            # Execute Calendar sync with retry logic
            result = await token_manager.with_retry_and_refresh(
                user_id=user_id,
                operation=self._execute_calendar_sync,
                service="google",
                max_retries=self.max_retries
            )
            
            return SyncResult("calendar", SyncStatus.SUCCESS, "Calendar sync completed successfully", result)
            
        except Exception as e:
            logger.error(f"Calendar sync failed for user {user_id}: {str(e)}")
            
            # Diagnose the error for better user feedback
            try:
                issues = await service_diagnostics.diagnose_calendar_error(str(e), user_id)
                if issues:
                    primary_issue = issues[0]
                    return SyncResult("calendar", SyncStatus.FAILED, primary_issue.message, {
                        "error_code": primary_issue.error_code,
                        "suggestion": primary_issue.suggestion,
                        "recoverable": primary_issue.recoverable,
                        "diagnostics": service_diagnostics.format_issues_for_ui(issues)
                    })
            except Exception as diag_error:
                logger.error(f"Failed to diagnose Calendar error: {str(diag_error)}")
            
            return SyncResult("calendar", SyncStatus.FAILED, f"Calendar sync error: {str(e)}")
    
    async def _sync_hubspot_safe(self, user_id: str, force_refresh: bool = False) -> SyncResult:
        """HubSpot sync with comprehensive error handling"""
        try:
            # Ensure tokens are valid
            token_result = await token_manager.refresh_hubspot_tokens_if_needed(user_id, force_refresh)
            if not token_result:
                return SyncResult("hubspot", SyncStatus.FAILED, "Failed to refresh HubSpot tokens")
            
            # Execute HubSpot sync with retry logic
            result = await token_manager.with_retry_and_refresh(
                user_id=user_id,
                operation=self._execute_hubspot_sync,
                service="hubspot",
                max_retries=self.max_retries
            )
            
            return SyncResult("hubspot", SyncStatus.SUCCESS, "HubSpot sync completed successfully", result)
            
        except Exception as e:
            logger.error(f"HubSpot sync failed for user {user_id}: {str(e)}")
            
            # Diagnose the error for better user feedback
            try:
                issues = await service_diagnostics.diagnose_hubspot_error(str(e), user_id)
                if issues:
                    primary_issue = issues[0]
                    return SyncResult("hubspot", SyncStatus.FAILED, primary_issue.message, {
                        "error_code": primary_issue.error_code,
                        "suggestion": primary_issue.suggestion,
                        "recoverable": primary_issue.recoverable,
                        "diagnostics": service_diagnostics.format_issues_for_ui(issues)
                    })
            except Exception as diag_error:
                logger.error(f"Failed to diagnose HubSpot error: {str(diag_error)}")
            
            return SyncResult("hubspot", SyncStatus.FAILED, f"HubSpot sync error: {str(e)}")
    
    async def _execute_gmail_sync(self, user_id: str) -> Dict:
        """Execute Gmail sync task"""
        # Use the existing Celery task but await it directly
        task_result = sync_gmail_emails.delay(user_id)
        result = task_result.get(timeout=30)  # 30 second timeout
        return {"emails_synced": result.get("count", 0) if isinstance(result, dict) else 0}
    
    async def _execute_calendar_sync(self, user_id: str) -> Dict:
        """Execute Calendar sync task"""
        # Use the existing Celery task but await it directly
        task_result = sync_calendar_events.delay(user_id)
        result = task_result.get(timeout=30)  # 30 second timeout
        return {"events_synced": result.get("count", 0) if isinstance(result, dict) else 0}
    
    async def _execute_hubspot_sync(self, user_id: str) -> Dict:
        """Execute HubSpot sync task"""
        # Use the existing Celery task but await it directly
        task_result = sync_hubspot_contacts.delay(user_id)
        result = task_result.get(timeout=30)  # 30 second timeout
        return {"contacts_synced": result.get("count", 0) if isinstance(result, dict) else 0}
    
    async def _get_user_integrations(self, user_id: str) -> Optional[Dict]:
        """Get user integration status"""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    return None
                
                return {
                    "has_google": bool(user.google_access_token and user.google_refresh_token),
                    "has_hubspot": bool(user.hubspot_access_token and user.hubspot_refresh_token),
                    "email": user.email,
                    "name": user.name
                }
        except Exception as e:
            logger.error(f"Failed to get user integrations for {user_id}: {str(e)}")
            return None
    
    def _log_sync_summary(self, user_id: str, results: Dict[str, SyncResult]):
        """Log a summary of sync results"""
        success_count = sum(1 for r in results.values() if r.status == SyncStatus.SUCCESS)
        failed_count = sum(1 for r in results.values() if r.status == SyncStatus.FAILED)
        total_count = len(results)
        
        logger.info(f"Sync summary for user {user_id}: {success_count}/{total_count} successful, {failed_count} failed")
        
        # Log details for each service
        for service, result in results.items():
            if result.status == SyncStatus.SUCCESS:
                logger.info(f"✅ {service}: {result.message}")
            elif result.status == SyncStatus.FAILED:
                logger.error(f"❌ {service}: {result.message}")
            else:
                logger.warning(f"⚠️ {service}: {result.message}")
    
    async def get_last_sync_status(self, user_id: str) -> Dict[str, Any]:
        """Get the last sync status for a user (could be extended to store in DB)"""
        # For now, return a basic status - could be enhanced to store sync history
        user_info = await self._get_user_integrations(user_id)
        if not user_info:
            return {"error": "User not found"}
        
        return {
            "user_id": user_id,
            "integrations": user_info,
            "last_checked": datetime.utcnow().isoformat()
        }
    
    async def health_check(self, user_id: str) -> Dict[str, Any]:
        """Perform a comprehensive health check on all integrations with diagnostics"""
        logger.info(f"Running enhanced health check for user {user_id}")
        
        # Check cache first for better performance
        cached_result = await performance_monitor.cached_health_check(user_id)
        if cached_result:
            logger.info(f"Returning cached health check for user {user_id}")
            return cached_result
        
        user_info = await self._get_user_integrations(user_id)
        if not user_info:
            return {"status": "error", "message": "User not found"}
        
        health_status = {
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat(),
            "overall_status": "healthy",
            "services": {},
            "recommendations": {},
            "issues": []
        }
        
        # Get service recommendations
        try:
            recommendations = await service_diagnostics.get_service_recommendations(user_id)
            health_status["recommendations"] = recommendations
        except Exception as e:
            logger.error(f"Failed to get service recommendations: {str(e)}")
        
        # Check token validity for each service
        if user_info.get("has_google"):
            google_valid = await token_manager.refresh_google_tokens_if_needed(user_id)
            
            # Check for data health issues
            try:
                gmail_issues = await service_diagnostics.diagnose_gmail_error("", user_id)
                calendar_issues = await service_diagnostics.diagnose_calendar_error("", user_id)
                google_issues = gmail_issues + calendar_issues
                
                if google_issues:
                    health_status["issues"].extend(google_issues)
                    google_status = "degraded" if any(issue.severity.value in ["high", "critical"] for issue in google_issues) else "warning"
                else:
                    google_status = "healthy" if google_valid else "token_issues"
                
            except Exception as e:
                logger.error(f"Failed to check Google service health: {str(e)}")
                google_status = "healthy" if google_valid else "token_issues"
            
            health_status["services"]["google"] = {
                "status": google_status,
                "message": "Tokens valid" if google_valid else "Token refresh failed",
                "token_valid": str(google_valid).lower()
            }
        
        if user_info.get("has_hubspot"):
            hubspot_valid = await token_manager.refresh_hubspot_tokens_if_needed(user_id)
            
            # Check for data health issues
            try:
                hubspot_issues = await service_diagnostics.diagnose_hubspot_error("", user_id)
                
                if hubspot_issues:
                    health_status["issues"].extend(hubspot_issues)
                    hubspot_status = "degraded" if any(issue.severity.value in ["high", "critical"] for issue in hubspot_issues) else "warning"
                else:
                    hubspot_status = "healthy" if hubspot_valid else "token_issues"
                
            except Exception as e:
                logger.error(f"Failed to check HubSpot service health: {str(e)}")
                hubspot_status = "healthy" if hubspot_valid else "token_issues"
            
            health_status["services"]["hubspot"] = {
                "status": hubspot_status,
                "message": "Tokens valid" if hubspot_valid else "Token refresh failed",
                "token_valid": str(hubspot_valid).lower()
            }
        
        # Update overall status based on service health and issues
        critical_issues = any(issue.severity.value == "critical" for issue in health_status["issues"])
        high_issues = any(issue.severity.value == "high" for issue in health_status["issues"])
        service_issues = any(s["status"] in ["degraded", "token_issues"] for s in health_status["services"].values())
        
        if critical_issues:
            health_status["overall_status"] = "critical"
        elif high_issues or service_issues:
            health_status["overall_status"] = "degraded"
        elif health_status["issues"]:
            health_status["overall_status"] = "warning"
        
        # Format issues for UI
        health_status["formatted_issues"] = service_diagnostics.format_issues_for_ui(health_status["issues"])
        
        # Cache the result for better performance
        performance_monitor.cache_health_check(user_id, health_status)
        
        return health_status

# Global instance
sync_manager = SyncManager() 