import structlog
from typing import Dict, List, Optional, Any
from enum import Enum
from datetime import datetime, timedelta
import re
from database import AsyncSessionLocal, User, Email, HubspotContact, CalendarEvent
from sqlalchemy import select, func

logger = structlog.get_logger()

class ErrorSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ServiceIssue:
    def __init__(
        self, 
        service: str,
        issue_type: str,
        severity: ErrorSeverity,
        message: str,
        suggestion: str,
        recoverable: bool = True,
        error_code: Optional[str] = None
    ):
        self.service = service
        self.issue_type = issue_type
        self.severity = severity
        self.message = message
        self.suggestion = suggestion
        self.recoverable = recoverable
        self.error_code = error_code
        self.timestamp = datetime.utcnow()

class ServiceDiagnostics:
    """Advanced diagnostics for sync services with specific error analysis"""
    
    def __init__(self):
        self.gmail_patterns = {
            'quota_exceeded': r'quotaExceeded|quota.*exceeded|rate.*limit',
            'invalid_credentials': r'invalid_grant|unauthorized|401',
            'token_expired': r'token.*expired|invalid.*token',
            'permission_denied': r'forbidden|403|permission.*denied',
            'api_disabled': r'disabled|not.*enabled|api.*access',
            'network_error': r'network.*error|connection.*error|timeout',
            'gmail_api_error': r'gmail.*api.*error|backend.*error|503|502|500'
        }
        
        self.hubspot_patterns = {
            'rate_limit': r'rate.*limit|429|too.*many.*requests',
            'invalid_token': r'invalid.*token|unauthorized|401',
            'permission_denied': r'forbidden|403|insufficient.*scope',
            'property_error': r'property.*not.*found|invalid.*property',
            'contact_limit': r'contact.*limit|subscription.*limit',
            'api_error': r'internal.*error|500|502|503',
            'portal_suspended': r'portal.*suspended|account.*suspended'
        }
        
        self.calendar_patterns = {
            'calendar_not_found': r'calendar.*not.*found|404',
            'event_conflict': r'conflict|409|time.*conflict',
            'timezone_error': r'timezone|invalid.*datetime',
            'attendee_limit': r'attendee.*limit|too.*many.*attendees',
            'quota_exceeded': r'quotaExceeded|quota.*exceeded'
        }

    async def diagnose_gmail_error(self, error_message: str, user_id: str) -> List[ServiceIssue]:
        """Diagnose Gmail-specific errors with detailed analysis"""
        issues = []
        error_lower = error_message.lower()
        
        # Check for specific Gmail error patterns
        if re.search(self.gmail_patterns['quota_exceeded'], error_lower):
            issues.append(ServiceIssue(
                service="gmail",
                issue_type="quota_exceeded",
                severity=ErrorSeverity.HIGH,
                message="Gmail API quota exceeded",
                suggestion="Wait 24 hours for quota reset or enable paid quota in Google Cloud Console",
                recoverable=True,
                error_code="GMAIL_QUOTA_EXCEEDED"
            ))
        
        elif re.search(self.gmail_patterns['invalid_credentials'], error_lower):
            issues.append(ServiceIssue(
                service="gmail",
                issue_type="auth_error",
                severity=ErrorSeverity.CRITICAL,
                message="Gmail authentication failed - invalid credentials",
                suggestion="Reconnect your Google account through the integrations page",
                recoverable=True,
                error_code="GMAIL_AUTH_INVALID"
            ))
        
        elif re.search(self.gmail_patterns['token_expired'], error_lower):
            issues.append(ServiceIssue(
                service="gmail",
                issue_type="token_expired",
                severity=ErrorSeverity.MEDIUM,
                message="Gmail access token expired",
                suggestion="Token will be automatically refreshed. If issue persists, reconnect your account",
                recoverable=True,
                error_code="GMAIL_TOKEN_EXPIRED"
            ))
        
        elif re.search(self.gmail_patterns['permission_denied'], error_lower):
            issues.append(ServiceIssue(
                service="gmail",
                issue_type="permission_denied",
                severity=ErrorSeverity.HIGH,
                message="Insufficient permissions for Gmail access",
                suggestion="Reconnect Gmail with all required permissions (read, compose, calendar)",
                recoverable=True,
                error_code="GMAIL_PERMISSION_DENIED"
            ))
        
        elif re.search(self.gmail_patterns['api_disabled'], error_lower):
            issues.append(ServiceIssue(
                service="gmail",
                issue_type="api_disabled",
                severity=ErrorSeverity.CRITICAL,
                message="Gmail API is not enabled",
                suggestion="Enable Gmail API in Google Cloud Console for your project",
                recoverable=False,
                error_code="GMAIL_API_DISABLED"
            ))
        
        # Check for data consistency issues
        await self._check_gmail_data_health(user_id, issues)
        
        return issues

    async def diagnose_hubspot_error(self, error_message: str, user_id: str) -> List[ServiceIssue]:
        """Diagnose HubSpot-specific errors with detailed analysis"""
        issues = []
        error_lower = error_message.lower()
        
        if re.search(self.hubspot_patterns['rate_limit'], error_lower):
            issues.append(ServiceIssue(
                service="hubspot",
                issue_type="rate_limit",
                severity=ErrorSeverity.MEDIUM,
                message="HubSpot API rate limit exceeded",
                suggestion="Wait 10 minutes before retrying. Consider upgrading HubSpot plan for higher limits",
                recoverable=True,
                error_code="HUBSPOT_RATE_LIMIT"
            ))
        
        elif re.search(self.hubspot_patterns['invalid_token'], error_lower):
            issues.append(ServiceIssue(
                service="hubspot",
                issue_type="auth_error",
                severity=ErrorSeverity.CRITICAL,
                message="HubSpot authentication failed",
                suggestion="Reconnect your HubSpot account through the integrations page",
                recoverable=True,
                error_code="HUBSPOT_AUTH_INVALID"
            ))
        
        elif re.search(self.hubspot_patterns['permission_denied'], error_lower):
            issues.append(ServiceIssue(
                service="hubspot",
                issue_type="permission_denied",
                severity=ErrorSeverity.HIGH,
                message="Insufficient HubSpot permissions",
                suggestion="Reconnect HubSpot with admin permissions for contacts, deals, and companies",
                recoverable=True,
                error_code="HUBSPOT_PERMISSION_DENIED"
            ))
        
        elif re.search(self.hubspot_patterns['property_error'], error_lower):
            issues.append(ServiceIssue(
                service="hubspot",
                issue_type="property_error",
                severity=ErrorSeverity.LOW,
                message="HubSpot property configuration issue",
                suggestion="Some custom properties may not be synced. Check HubSpot property settings",
                recoverable=True,
                error_code="HUBSPOT_PROPERTY_ERROR"
            ))
        
        elif re.search(self.hubspot_patterns['portal_suspended'], error_lower):
            issues.append(ServiceIssue(
                service="hubspot",
                issue_type="portal_suspended",
                severity=ErrorSeverity.CRITICAL,
                message="HubSpot portal is suspended",
                suggestion="Contact HubSpot support to resolve portal suspension",
                recoverable=False,
                error_code="HUBSPOT_PORTAL_SUSPENDED"
            ))
        
        # Check for data consistency issues
        await self._check_hubspot_data_health(user_id, issues)
        
        return issues

    async def diagnose_calendar_error(self, error_message: str, user_id: str) -> List[ServiceIssue]:
        """Diagnose Calendar-specific errors with detailed analysis"""
        issues = []
        error_lower = error_message.lower()
        
        if re.search(self.calendar_patterns['calendar_not_found'], error_lower):
            issues.append(ServiceIssue(
                service="calendar",
                issue_type="calendar_not_found",
                severity=ErrorSeverity.MEDIUM,
                message="Primary calendar not accessible",
                suggestion="Check if primary calendar exists and is accessible with current permissions",
                recoverable=True,
                error_code="CALENDAR_NOT_FOUND"
            ))
        
        elif re.search(self.calendar_patterns['event_conflict'], error_lower):
            issues.append(ServiceIssue(
                service="calendar",
                issue_type="event_conflict",
                severity=ErrorSeverity.LOW,
                message="Calendar event time conflict",
                suggestion="Event conflicts with existing calendar entry. Choose different time",
                recoverable=True,
                error_code="CALENDAR_CONFLICT"
            ))
        
        elif re.search(self.calendar_patterns['timezone_error'], error_lower):
            issues.append(ServiceIssue(
                service="calendar",
                issue_type="timezone_error",
                severity=ErrorSeverity.MEDIUM,
                message="Calendar timezone configuration issue",
                suggestion="Verify timezone settings in Google Calendar and try again",
                recoverable=True,
                error_code="CALENDAR_TIMEZONE_ERROR"
            ))
        
        # Check for data consistency issues
        await self._check_calendar_data_health(user_id, issues)
        
        return issues

    async def _check_gmail_data_health(self, user_id: str, issues: List[ServiceIssue]):
        """Check Gmail data health and consistency"""
        try:
            async with AsyncSessionLocal() as session:
                # Check if user has emails but no recent activity
                result = await session.execute(
                    select(
                        func.count(Email.id).label("total_emails"),
                        func.max(Email.created_at).label("last_sync")
                    ).where(Email.user_id == user_id)
                )
                stats = result.first()
                
                if stats.total_emails == 0:
                    issues.append(ServiceIssue(
                        service="gmail",
                        issue_type="no_data",
                        severity=ErrorSeverity.MEDIUM,
                        message="No Gmail data found",
                        suggestion="Trigger initial Gmail sync or check if Gmail account has accessible emails",
                        recoverable=True,
                        error_code="GMAIL_NO_DATA"
                    ))
                
                elif stats.last_sync and (datetime.utcnow() - stats.last_sync) > timedelta(days=7):
                    issues.append(ServiceIssue(
                        service="gmail",
                        issue_type="stale_data",
                        severity=ErrorSeverity.LOW,
                        message="Gmail data is outdated",
                        suggestion="Last sync was over 7 days ago. Consider manual sync",
                        recoverable=True,
                        error_code="GMAIL_STALE_DATA"
                    ))
                    
        except Exception as e:
            logger.error(f"Gmail data health check failed: {str(e)}")

    async def _check_hubspot_data_health(self, user_id: str, issues: List[ServiceIssue]):
        """Check HubSpot data health and consistency"""
        try:
            async with AsyncSessionLocal() as session:
                # Check if user has HubSpot contacts
                result = await session.execute(
                    select(
                        func.count(HubspotContact.id).label("total_contacts"),
                        func.max(HubspotContact.created_at).label("last_sync")
                    ).where(HubspotContact.user_id == user_id)
                )
                stats = result.first()
                
                if stats.total_contacts == 0:
                    issues.append(ServiceIssue(
                        service="hubspot",
                        issue_type="no_data",
                        severity=ErrorSeverity.MEDIUM,
                        message="No HubSpot data found",
                        suggestion="Trigger initial HubSpot sync or verify HubSpot account has contacts",
                        recoverable=True,
                        error_code="HUBSPOT_NO_DATA"
                    ))
                    
        except Exception as e:
            logger.error(f"HubSpot data health check failed: {str(e)}")

    async def _check_calendar_data_health(self, user_id: str, issues: List[ServiceIssue]):
        """Check Calendar data health and consistency"""
        try:
            async with AsyncSessionLocal() as session:
                # Check if user has calendar events
                result = await session.execute(
                    select(
                        func.count(CalendarEvent.id).label("total_events"),
                        func.max(CalendarEvent.created_at).label("last_sync")
                    ).where(CalendarEvent.user_id == user_id)
                )
                stats = result.first()
                
                if stats.total_events == 0:
                    issues.append(ServiceIssue(
                        service="calendar",
                        issue_type="no_data",
                        severity=ErrorSeverity.LOW,
                        message="No Calendar events found",
                        suggestion="Calendar may be empty or sync permissions insufficient",
                        recoverable=True,
                        error_code="CALENDAR_NO_DATA"
                    ))
                    
        except Exception as e:
            logger.error(f"Calendar data health check failed: {str(e)}")

    async def get_service_recommendations(self, user_id: str) -> Dict[str, List[str]]:
        """Get proactive recommendations for each service"""
        recommendations = {
            "gmail": [],
            "hubspot": [], 
            "calendar": []
        }
        
        try:
            async with AsyncSessionLocal() as session:
                # Check user's service status
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    return recommendations
                
                # Gmail recommendations
                if user.google_access_token:
                    if user.google_token_expires_at:
                        time_until_expiry = user.google_token_expires_at - datetime.utcnow()
                        if time_until_expiry.total_seconds() < 3600:  # Less than 1 hour
                            recommendations["gmail"].append("Google token expires soon - will auto-refresh")
                    
                    # Check email sync frequency
                    email_result = await session.execute(
                        select(func.max(Email.created_at)).where(Email.user_id == user_id)
                    )
                    last_email_sync = email_result.scalar()
                    
                    if not last_email_sync:
                        recommendations["gmail"].append("No emails synced yet - trigger initial sync")
                    elif (datetime.utcnow() - last_email_sync) > timedelta(hours=24):
                        recommendations["gmail"].append("Email sync is 24+ hours old - consider refresh")
                
                # HubSpot recommendations
                if user.hubspot_access_token:
                    contact_result = await session.execute(
                        select(func.count(HubspotContact.id)).where(HubspotContact.user_id == user_id)
                    )
                    contact_count = contact_result.scalar()
                    
                    if contact_count == 0:
                        recommendations["hubspot"].append("No HubSpot contacts synced - verify account access")
                    elif contact_count < 5:
                        recommendations["hubspot"].append("Low contact count - ensure HubSpot has data")
                
                # Calendar recommendations
                if user.google_access_token:
                    event_result = await session.execute(
                        select(func.count(CalendarEvent.id)).where(CalendarEvent.user_id == user_id)
                    )
                    event_count = event_result.scalar()
                    
                    if event_count == 0:
                        recommendations["calendar"].append("No calendar events found - calendar may be empty")
                
        except Exception as e:
            logger.error(f"Failed to get service recommendations: {str(e)}")
        
        return recommendations

    def format_issues_for_ui(self, issues: List[ServiceIssue]) -> Dict[str, Any]:
        """Format issues for frontend display"""
        if not issues:
            return {"status": "healthy", "issues": []}
        
        severity_counts = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0
        }
        
        formatted_issues = []
        
        for issue in issues:
            severity_counts[issue.severity.value] += 1
            formatted_issues.append({
                "service": issue.service,
                "type": issue.issue_type,
                "severity": issue.severity.value,
                "message": issue.message,
                "suggestion": issue.suggestion,
                "recoverable": issue.recoverable,
                "error_code": issue.error_code,
                "timestamp": issue.timestamp.isoformat()
            })
        
        # Determine overall status
        if severity_counts["critical"] > 0:
            overall_status = "critical"
        elif severity_counts["high"] > 0:
            overall_status = "degraded"
        elif severity_counts["medium"] > 0:
            overall_status = "warning"
        else:
            overall_status = "healthy"
        
        return {
            "status": overall_status,
            "issues": formatted_issues,
            "severity_counts": severity_counts,
            "total_issues": len(issues)
        }

# Global instance
service_diagnostics = ServiceDiagnostics() 