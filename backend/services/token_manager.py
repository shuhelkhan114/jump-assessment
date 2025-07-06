import structlog
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
import httpx
from sqlalchemy import select, update
from database import AsyncSessionLocal, User
from config import get_settings

logger = structlog.get_logger()

class TokenManager:
    """Centralized token management for Google and HubSpot APIs"""
    
    def __init__(self):
        self.settings = get_settings()
        
    async def refresh_google_tokens_if_needed(self, user_id: str, force_refresh: bool = False) -> bool:
        """
        Check if Google tokens need refresh and refresh them proactively
        Returns True if tokens are valid, False if refresh failed
        """
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    logger.error(f"User {user_id} not found for token refresh")
                    return False
                
                if not user.google_refresh_token:
                    logger.error(f"User {user_id} has no Google refresh token")
                    return False
                
                # Check if token needs refresh (within 10 minutes of expiry or force refresh)
                needs_refresh = force_refresh
                if user.google_token_expires_at:
                    time_until_expiry = user.google_token_expires_at - datetime.utcnow()
                    needs_refresh = needs_refresh or time_until_expiry.total_seconds() < 600  # 10 minutes
                else:
                    # No expiry time recorded, assume it needs refresh
                    needs_refresh = True
                
                if not needs_refresh:
                    logger.debug(f"Google tokens for user {user_id} are still valid")
                    return True
                
                logger.info(f"Refreshing Google tokens for user {user_id}")
                
                # Refresh the tokens
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://oauth2.googleapis.com/token",
                        data={
                            "client_id": self.settings.google_client_id,
                            "client_secret": self.settings.google_client_secret,
                            "refresh_token": user.google_refresh_token,
                            "grant_type": "refresh_token"
                        }
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"Failed to refresh Google tokens for user {user_id}: {response.text}")
                        return False
                    
                    token_data = response.json()
                    
                    # Update user tokens
                    new_access_token = token_data["access_token"]
                    expires_in = token_data.get("expires_in", 3600)  # Default 1 hour
                    new_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                    
                    # Update refresh token if provided (sometimes Google provides a new one)
                    new_refresh_token = token_data.get("refresh_token", user.google_refresh_token)
                    
                    await session.execute(
                        update(User)
                        .where(User.id == user_id)
                        .values(
                            google_access_token=new_access_token,
                            google_refresh_token=new_refresh_token,
                            google_token_expires_at=new_expires_at
                        )
                    )
                    await session.commit()
                    
                    logger.info(f"Successfully refreshed Google tokens for user {user_id}")
                    return True
                    
        except Exception as e:
            logger.error(f"Error refreshing Google tokens for user {user_id}: {str(e)}")
            return False
    
    async def refresh_hubspot_tokens_if_needed(self, user_id: str, force_refresh: bool = False) -> bool:
        """
        Check if HubSpot tokens need refresh and refresh them proactively
        Returns True if tokens are valid, False if refresh failed
        """
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(User).where(User.id == user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    logger.error(f"User {user_id} not found for token refresh")
                    return False
                
                if not user.hubspot_refresh_token:
                    logger.error(f"User {user_id} has no HubSpot refresh token")
                    return False
                
                # Check if token needs refresh (within 10 minutes of expiry or force refresh)
                needs_refresh = force_refresh
                if user.hubspot_token_expires_at:
                    time_until_expiry = user.hubspot_token_expires_at - datetime.utcnow()
                    needs_refresh = needs_refresh or time_until_expiry.total_seconds() < 600  # 10 minutes
                else:
                    # No expiry time recorded, assume it needs refresh
                    needs_refresh = True
                
                if not needs_refresh:
                    logger.debug(f"HubSpot tokens for user {user_id} are still valid")
                    return True
                
                logger.info(f"Refreshing HubSpot tokens for user {user_id}")
                
                # Refresh the tokens
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.hubapi.com/oauth/v1/token",
                        data={
                            "grant_type": "refresh_token",
                            "client_id": self.settings.hubspot_client_id,
                            "client_secret": self.settings.hubspot_client_secret,
                            "refresh_token": user.hubspot_refresh_token
                        }
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"Failed to refresh HubSpot tokens for user {user_id}: {response.text}")
                        return False
                    
                    token_data = response.json()
                    
                    # Update user tokens
                    new_access_token = token_data["access_token"]
                    expires_in = token_data.get("expires_in", 21600)  # Default 6 hours
                    new_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
                    
                    # Update refresh token if provided
                    new_refresh_token = token_data.get("refresh_token", user.hubspot_refresh_token)
                    
                    await session.execute(
                        update(User)
                        .where(User.id == user_id)
                        .values(
                            hubspot_access_token=new_access_token,
                            hubspot_refresh_token=new_refresh_token,
                            hubspot_token_expires_at=new_expires_at
                        )
                    )
                    await session.commit()
                    
                    logger.info(f"Successfully refreshed HubSpot tokens for user {user_id}")
                    return True
                    
        except Exception as e:
            logger.error(f"Error refreshing HubSpot tokens for user {user_id}: {str(e)}")
            return False
    
    async def ensure_valid_tokens(self, user_id: str, services: list = None) -> Dict[str, bool]:
        """
        Ensure all specified services have valid tokens
        Returns dict with service: success status
        """
        if services is None:
            services = ["google", "hubspot"]
        
        results = {}
        
        if "google" in services:
            results["google"] = await self.refresh_google_tokens_if_needed(user_id)
        
        if "hubspot" in services:
            results["hubspot"] = await self.refresh_hubspot_tokens_if_needed(user_id)
        
        return results
    
    async def with_retry_and_refresh(
        self, 
        user_id: str, 
        operation: Callable,
        service: str = "google",
        max_retries: int = 2,
        *args,
        **kwargs
    ) -> Any:
        """
        Execute an operation with automatic token refresh and retry on auth errors
        """
        for attempt in range(max_retries + 1):
            try:
                # Ensure tokens are valid before operation
                if service == "google":
                    token_valid = await self.refresh_google_tokens_if_needed(user_id)
                elif service == "hubspot":
                    token_valid = await self.refresh_hubspot_tokens_if_needed(user_id)
                else:
                    logger.error(f"Unknown service: {service}")
                    raise ValueError(f"Unknown service: {service}")
                
                if not token_valid:
                    raise Exception(f"Failed to refresh {service} tokens for user {user_id}")
                
                # Execute the operation
                result = await operation(*args, **kwargs)
                return result
                
            except Exception as e:
                error_str = str(e).lower()
                is_auth_error = any(keyword in error_str for keyword in [
                    "unauthorized", "invalid_grant", "token", "expired", "authentication"
                ])
                
                if is_auth_error and attempt < max_retries:
                    logger.warning(f"Auth error on attempt {attempt + 1}, refreshing tokens and retrying: {str(e)}")
                    # Force refresh tokens on auth error
                    if service == "google":
                        await self.refresh_google_tokens_if_needed(user_id, force_refresh=True)
                    elif service == "hubspot":
                        await self.refresh_hubspot_tokens_if_needed(user_id, force_refresh=True)
                    continue
                else:
                    # Re-raise the error if not auth-related or max retries reached
                    raise e

# Global instance
token_manager = TokenManager() 