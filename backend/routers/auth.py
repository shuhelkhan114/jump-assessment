from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import Optional
import structlog
import secrets
import httpx
from urllib.parse import urlencode

from config import get_settings
from auth import (
    get_google_oauth_flow, 
    create_access_token, 
    verify_google_token, 
    create_user_from_google,
    get_current_user
)
from database import get_user_by_email, AsyncSessionLocal, User, select
from tasks.auto_sync_tasks import trigger_initial_sync_if_needed, trigger_gmail_sync, trigger_hubspot_sync

logger = structlog.get_logger()
settings = get_settings()

router = APIRouter()

# Pydantic models
class Token(BaseModel):
    access_token: str
    token_type: str

class GoogleAuthRequest(BaseModel):
    code: str
    state: Optional[str] = None

class HubSpotAuthRequest(BaseModel):
    code: str
    state: Optional[str] = None

# OAuth state storage (in production, use Redis or database)
oauth_states = {}

@router.get("/google/login")
async def google_login():
    """Initiate Google OAuth flow"""
    try:
        flow = get_google_oauth_flow()
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        oauth_states[state] = {"provider": "google"}
        
        authorization_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true',
            prompt='consent',  # Force consent to ensure refresh token is provided
            state=state
        )
        
        # Redirect directly to Google OAuth instead of returning JSON
        return RedirectResponse(url=authorization_url)
    except Exception as e:
        logger.error(f"Google login initiation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate Google login"
        )

@router.get("/google/callback")
async def google_callback(code: str, state: str):
    """Handle Google OAuth callback"""
    try:
        # Verify state
        if state not in oauth_states:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter"
            )
        
        # Clean up state
        del oauth_states[state]
        
        flow = get_google_oauth_flow()
        flow.fetch_token(code=code)
        
        # Get user info from Google
        credentials = flow.credentials
        id_info = await verify_google_token(credentials.id_token)
        
        # Detailed debugging of credentials object
        print(f"=== GOOGLE CREDENTIALS DEBUG ===")
        print(f"credentials.token: {bool(credentials.token)} (length: {len(credentials.token) if credentials.token else 0})")
        print(f"credentials.refresh_token: {bool(credentials.refresh_token)} (length: {len(credentials.refresh_token) if credentials.refresh_token else 0})")
        print(f"credentials.expired: {credentials.expired}")
        print(f"credentials.expiry: {credentials.expiry}")
        print(f"credentials object type: {type(credentials)}")
        if credentials.refresh_token:
            print(f"Refresh token preview: {credentials.refresh_token[:20]}...")
        else:
            print("❌ NO REFRESH TOKEN PROVIDED BY GOOGLE")
        
        # Create or update user
        tokens = {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "expires_in": credentials.expires_in if hasattr(credentials, 'expires_in') else 3600
        }
        
        # Debug logging for refresh token  
        logger.info(f"Google OAuth callback tokens - Access token: {bool(tokens['access_token'])}, Refresh token: {bool(tokens['refresh_token'])}")
        print(f"Final tokens dict - Access: {bool(tokens['access_token'])}, Refresh: {bool(tokens['refresh_token'])}")
        
        user = await create_user_from_google(id_info, tokens)
        
        # Trigger Gmail sync for Google OAuth completion
        trigger_gmail_sync.delay(user["id"])
        
        # Create JWT token
        access_token = create_access_token(data={"sub": user["email"]})
        
        # Redirect to frontend with token
        redirect_url = f"{settings.frontend_url}/auth/callback?token={access_token}"
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        logger.error(f"Google callback failed: {str(e)}")
        error_url = f"{settings.frontend_url}/auth/error?error=google_auth_failed"
        return RedirectResponse(url=error_url)

@router.post("/google/token", response_model=Token)
async def google_token(auth_request: GoogleAuthRequest):
    """Exchange Google authorization code for access token"""
    try:
        # Verify state if provided
        if auth_request.state and auth_request.state not in oauth_states:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter"
            )
        
        # Clean up state
        if auth_request.state:
            del oauth_states[auth_request.state]
        
        flow = get_google_oauth_flow()
        flow.fetch_token(code=auth_request.code)
        
        # Get user info from Google
        credentials = flow.credentials
        id_info = await verify_google_token(credentials.id_token)
        
        # Create or update user
        tokens = {
            "access_token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "expires_in": credentials.expires_in if hasattr(credentials, 'expires_in') else 3600
        }
        
        # Debug logging for refresh token
        logger.info(f"Google OAuth tokens received - Access token: {bool(tokens['access_token'])}, Refresh token: {bool(tokens['refresh_token'])}")
        
        user = await create_user_from_google(id_info, tokens)
        
        # Trigger robust initial sync for Google OAuth completion
        from tasks.auto_sync_tasks import robust_initial_sync
        robust_initial_sync.delay(user["id"], force_refresh=True)
        
        # Create JWT token
        access_token = create_access_token(data={"sub": user["email"]})
        
        return {"access_token": access_token, "token_type": "bearer"}
        
    except Exception as e:
        logger.error(f"Google token exchange failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange Google authorization code"
        )

@router.get("/hubspot/login")
async def hubspot_login(current_user: dict = Depends(get_current_user)):
    """Initiate HubSpot OAuth flow"""
    try:
        if not settings.hubspot_client_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="HubSpot OAuth not configured"
            )
        
        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)
        oauth_states[state] = {"provider": "hubspot", "user_id": current_user["id"]}
        
        # HubSpot OAuth parameters
        params = {
            "client_id": settings.hubspot_client_id,
            "redirect_uri": settings.hubspot_redirect_uri,
            "scope": "oauth crm.objects.owners.read",
            "optional_scope": "crm.objects.contacts.read crm.objects.contacts.write crm.objects.companies.read crm.objects.deals.read",
            "state": state
        }
        
        authorization_url = f"https://app.hubspot.com/oauth/authorize?{urlencode(params)}"
        
        return {"authorization_url": authorization_url}
        
    except Exception as e:
        logger.error(f"HubSpot login initiation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate HubSpot login"
        )

@router.get("/hubspot/callback")
async def hubspot_callback(code: str, state: str):
    """Handle HubSpot OAuth callback"""
    try:
        # Verify state
        if state not in oauth_states:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid state parameter"
            )
        
        # Get state data before cleaning up
        oauth_state_data = oauth_states[state]
        
        # Clean up state
        del oauth_states[state]
        
        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://api.hubapi.com/oauth/v1/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.hubspot_client_id,
                    "client_secret": settings.hubspot_client_secret,
                    "redirect_uri": settings.hubspot_redirect_uri,
                    "code": code
                }
            )
            
            if token_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange HubSpot authorization code"
                )
            
            tokens = token_response.json()
        
        # Get current user from state (we need to identify the user)
        user_id = oauth_state_data.get("user_id")
        
        if user_id:
            # Update user with HubSpot tokens
            await update_user_hubspot_tokens(user_id, tokens)
            
            # Trigger robust sync for HubSpot OAuth completion
            from tasks.auto_sync_tasks import robust_trigger_sync
            robust_trigger_sync.delay(user_id, services=["hubspot"])
        
        redirect_url = f"{settings.frontend_url}/auth/hubspot/success"
        return RedirectResponse(url=redirect_url)
        
    except Exception as e:
        logger.error(f"HubSpot callback failed: {str(e)}")
        error_url = f"{settings.frontend_url}/auth/error?error=hubspot_auth_failed"
        return RedirectResponse(url=error_url)

@router.post("/hubspot/token")
async def hubspot_token(auth_request: HubSpotAuthRequest, current_user: dict = Depends(get_current_user)):
    """Exchange HubSpot authorization code for access token"""
    try:
        # Exchange code for tokens
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://api.hubapi.com/oauth/v1/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.hubspot_client_id,
                    "client_secret": settings.hubspot_client_secret,
                    "redirect_uri": settings.hubspot_redirect_uri,
                    "code": auth_request.code
                }
            )
            
            if token_response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange HubSpot authorization code"
                )
            
            tokens = token_response.json()
        
        # Update user with HubSpot tokens
        await update_user_hubspot_tokens(current_user["id"], tokens)
        
        # Trigger robust sync for HubSpot OAuth completion
        from tasks.auto_sync_tasks import robust_trigger_sync
        robust_trigger_sync.delay(current_user["id"], services=["hubspot"])
        
        return {"message": "HubSpot authentication successful"}
        
    except Exception as e:
        logger.error(f"HubSpot token exchange failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to exchange HubSpot authorization code"
        )

@router.get("/status")
async def auth_status(current_user: dict = Depends(get_current_user)):
    """Get authentication status"""
    return {
        "user": {
            "id": current_user["id"],
            "email": current_user["email"],
            "name": current_user["name"]
        },
        "integrations": {
            "google": bool(current_user.get("google_access_token")),
            "hubspot": bool(current_user.get("hubspot_access_token"))
        }
    }

@router.post("/refresh", response_model=Token)
async def refresh_token(current_user: dict = Depends(get_current_user)):
    """Refresh JWT access token"""
    try:
        # Create a new JWT token for the authenticated user
        access_token = create_access_token(data={"sub": current_user["email"]})
        return {"access_token": access_token, "token_type": "bearer"}
    except Exception as e:
        logger.error(f"Token refresh failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to refresh token"
        )

@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """Logout user"""
    # In a real implementation, you might want to blacklist the token
    # For now, just return success
    return {"message": "Logged out successfully"}

async def update_user_hubspot_tokens(user_id: str, tokens: dict):
    """Update user's HubSpot tokens"""
    from datetime import datetime, timedelta
    
    expires_at = None
    if tokens.get("expires_in"):
        expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            user.hubspot_access_token = tokens.get("access_token")
            user.hubspot_refresh_token = tokens.get("refresh_token")
            user.hubspot_token_expires_at = expires_at
            user.updated_at = datetime.utcnow()
            
            await session.commit() 