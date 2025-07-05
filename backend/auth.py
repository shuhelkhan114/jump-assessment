from fastapi import HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import structlog

from config import get_settings
from database import get_user_by_email, get_user_by_google_id, create_user

logger = structlog.get_logger()
settings = get_settings()

# Security
security = HTTPBearer()

# Google OAuth configuration
GOOGLE_CLIENT_ID = settings.google_client_id
GOOGLE_CLIENT_SECRET = settings.google_client_secret
GOOGLE_REDIRECT_URI = settings.google_redirect_uri

# Scopes for Google OAuth
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events"
]

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create JWT access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt

def verify_token(token: str) -> Dict[str, Any]:
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        email: str = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing subject"
            )
        return payload
    except JWTError as e:
        logger.error(f"JWT verification failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Get current authenticated user"""
    token = credentials.credentials
    payload = verify_token(token)
    
    user = await get_user_by_email(payload["sub"])
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    return dict(user)

def get_google_oauth_flow():
    """Get Google OAuth flow"""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth not configured"
        )
    
    flow = Flow.from_client_config(
        client_config={
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [GOOGLE_REDIRECT_URI]
            }
        },
        scopes=GOOGLE_SCOPES
    )
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow

async def verify_google_token(token: str) -> Dict[str, Any]:
    """Verify Google ID token"""
    try:
        idinfo = id_token.verify_oauth2_token(token, Request(), GOOGLE_CLIENT_ID)
        
        if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
            raise ValueError('Wrong issuer.')
        
        return idinfo
    except ValueError as e:
        logger.error(f"Google token verification failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google token"
        )

async def create_user_from_google(google_user_info: dict, tokens: dict) -> dict:
    """Create user from Google user info"""
    user_data = {
        "email": google_user_info["email"],
        "name": google_user_info.get("name"),
        "google_id": google_user_info["sub"]
    }
    
    # Check if user already exists
    existing_user = await get_user_by_email(user_data["email"])
    if existing_user:
        # Update Google ID if not set
        if not existing_user["google_id"]:
            # Update user with Google ID and tokens
            await update_user_google_tokens(existing_user["id"], google_user_info["sub"], tokens)
        return dict(existing_user)
    
    # Create new user
    user = await create_user(user_data)
    
    # Update with Google tokens
    await update_user_google_tokens(user["id"], google_user_info["sub"], tokens)
    
    return dict(user)

async def update_user_google_tokens(user_id: str, google_id: str, tokens: dict):
    """Update user's Google tokens"""
    from database import AsyncSessionLocal, User, select
    
    expires_at = None
    if tokens.get("expires_in"):
        expires_at = datetime.utcnow() + timedelta(seconds=tokens["expires_in"])
    
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if user:
            user.google_id = google_id
            user.google_access_token = tokens.get("access_token")
            user.google_refresh_token = tokens.get("refresh_token")
            user.google_token_expires_at = expires_at
            user.updated_at = datetime.utcnow()
            
            await session.commit()

async def refresh_google_token(user_id: str) -> Optional[str]:
    """Refresh Google access token"""
    from database import AsyncSessionLocal, User, select
    
    # Get user's refresh token
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user or not user.google_refresh_token:
            return None
        
        try:
            # TODO: Implement token refresh logic
            # This would involve calling Google's token refresh endpoint
            # For now, return None to indicate refresh needed
            return None
        except Exception as e:
            logger.error(f"Failed to refresh Google token: {str(e)}")
            return None

def require_google_auth(user: dict = Depends(get_current_user)) -> dict:
    """Require Google authentication"""
    if not user.get("google_access_token"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google authentication required"
        )
    return user

def require_hubspot_auth(user: dict = Depends(get_current_user)) -> dict:
    """Require HubSpot authentication"""
    if not user.get("hubspot_access_token"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="HubSpot authentication required"
        )
    return user 