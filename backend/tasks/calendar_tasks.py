"""
Calendar sync tasks for Google Calendar integration
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
import structlog
import json
from celery_app import celery_app
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from database import User, CalendarEvent
from config import get_settings
from services.gmail_service import gmail_service
from services.openai_service import openai_service

logger = structlog.get_logger()
settings = get_settings()

# Create synchronous database engine for Celery tasks
sync_engine = create_engine(settings.database_url, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine)

@celery_app.task(bind=True, max_retries=3)
def sync_calendar_events(self, user_id: str, days_forward: int = 30):
    """Sync Google Calendar events for a user"""
    try:
        logger.info(f"Starting calendar sync for user {user_id}")
        
        # Run sync function
        result = _sync_calendar_events_sync(user_id, days_forward)
        
        logger.info(f"Calendar sync completed for user {user_id}: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Calendar sync failed for user {user_id}: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_calendar_events_sync(user_id: str, days_forward: int = 30) -> Dict[str, Any]:
    """Sync implementation of calendar events sync"""
    with SyncSessionLocal() as session:
        # Get user with OAuth tokens
        result = session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise Exception(f"User {user_id} not found")
        
        if not user.google_access_token:
            raise Exception(f"User {user_id} has no Google access token")
        
        # Initialize Gmail service with enhanced token refresh
        try:
            if not gmail_service.initialize_service(
                user.google_access_token,
                user.google_refresh_token or "",
                user_id=user_id,
                token_update_callback=update_user_google_tokens
            ):
                # More specific error handling
                if not user.google_refresh_token:
                    raise Exception(f"Calendar service initialization failed for user {user_id}: Missing refresh token. Please reconnect your Google account.")
                else:
                    raise Exception(f"Calendar service initialization failed for user {user_id}: Token may be expired or invalid. Please reconnect your Google account.")
        except Exception as init_error:
            logger.error(f"Calendar service initialization error for user {user_id}: {str(init_error)}")
            raise Exception(f"Failed to initialize Calendar service for user {user_id}: {str(init_error)}")
        
        # Get existing calendar event IDs to avoid duplicates
        existing_result = session.execute(
            select(CalendarEvent.google_event_id).where(CalendarEvent.user_id == user_id)
        )
        existing_event_ids = {row[0] for row in existing_result.fetchall()}
        
        try:
            # Fetch events from Google Calendar (using asyncio.run for the async service call)
            events = asyncio.run(gmail_service.list_calendar_events(days_forward=days_forward))
            
        except Exception as api_error:
            # Check if this is a token-related error
            if "invalid_grant" in str(api_error).lower() or "unauthorized" in str(api_error).lower():
                logger.error(f"Google API authentication error for user {user_id}: {str(api_error)}")
                raise Exception(f"Google authentication expired for user {user_id}. Please reconnect your Google account.")
            else:
                logger.error(f"Google API error for user {user_id}: {str(api_error)}")
                raise Exception(f"Failed to fetch calendar events from Google Calendar for user {user_id}: {str(api_error)}")
        
        new_events = []
        updated_events = []
        processed_count = 0
        
        for event_data in events:
            try:
                google_event_id = event_data['google_event_id']
                processed_count += 1
                
                # Check if we already have this event
                if google_event_id in existing_event_ids:
                    # Update existing event
                    existing_event_result = session.execute(
                        select(CalendarEvent).where(
                            CalendarEvent.user_id == user_id,
                            CalendarEvent.google_event_id == google_event_id
                        )
                    )
                    existing_event = existing_event_result.scalar_one_or_none()
                    
                    if existing_event:
                        # Update fields that might have changed
                        existing_event.title = event_data['title']
                        existing_event.description = event_data['description']
                        existing_event.location = event_data['location']
                        existing_event.start_datetime = event_data['start_datetime']
                        existing_event.end_datetime = event_data['end_datetime']
                        existing_event.start_date = event_data['start_date']
                        existing_event.end_date = event_data['end_date']
                        existing_event.is_all_day = event_data['is_all_day']
                        existing_event.status = event_data['status']
                        existing_event.organizer_email = event_data['organizer_email']
                        existing_event.organizer_name = event_data['organizer_name']
                        existing_event.attendees = json.dumps(event_data['attendees'])
                        existing_event.updated_at = datetime.utcnow()
                        
                        updated_events.append(existing_event)
                    continue
                
                # Create new calendar event entry
                calendar_event = CalendarEvent(
                    user_id=user_id,
                    google_event_id=google_event_id,
                    calendar_id='primary',
                    title=event_data['title'],
                    description=event_data['description'],
                    location=event_data['location'],
                    start_datetime=event_data['start_datetime'],
                    end_datetime=event_data['end_datetime'],
                    start_date=event_data['start_date'],
                    end_date=event_data['end_date'],
                    is_all_day=event_data['is_all_day'],
                    status=event_data['status'],
                    organizer_email=event_data['organizer_email'],
                    organizer_name=event_data['organizer_name'],
                    attendees=json.dumps(event_data['attendees']),
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                
                session.add(calendar_event)
                new_events.append(calendar_event)
                
            except Exception as event_error:
                logger.error(f"Failed to process calendar event {event_data.get('google_event_id', 'unknown')}: {str(event_error)}")
                continue
        
        # Commit all changes
        session.commit()
        
        # Generate embeddings for new events
        embedding_tasks = []
        for event in new_events:
            try:
                # Create content for embedding (combining title, description, location)
                content_parts = []
                if event.title:
                    content_parts.append(f"Event: {event.title}")
                if event.description:
                    content_parts.append(f"Description: {event.description}")
                if event.location:
                    content_parts.append(f"Location: {event.location}")
                if event.organizer_name:
                    content_parts.append(f"Organizer: {event.organizer_name}")
                
                # Add attendee information
                if event.attendees:
                    try:
                        attendees_data = json.loads(event.attendees)
                        attendee_names = [att.get('displayName', att.get('email', '')) for att in attendees_data if att.get('displayName') or att.get('email')]
                        if attendee_names:
                            content_parts.append(f"Attendees: {', '.join(attendee_names)}")
                    except:
                        pass
                
                content = "\n".join(content_parts)
                if content.strip():
                    embedding_tasks.append((event.id, content))
                
            except Exception as e:
                logger.error(f"Failed to prepare embedding for calendar event {event.id}: {str(e)}")
        
        # Generate embeddings
        for event_id, content in embedding_tasks:
            try:
                embedding = asyncio.run(openai_service.generate_embedding(content))
                if embedding:
                    # Update event with embedding
                    session.execute(
                        CalendarEvent.__table__.update()
                        .where(CalendarEvent.id == event_id)
                        .values(embedding=embedding)
                    )
            except Exception as e:
                logger.error(f"Failed to generate embedding for calendar event {event_id}: {str(e)}")
        
        # Final commit for embeddings
        session.commit()
        
        return {
            "user_id": user_id,
            "total_events_fetched": len(events),
            "events_processed": processed_count,
            "new_events": len(new_events),
            "updated_events": len(updated_events),
            "synced_at": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True, max_retries=3)
def sync_all_users_calendar(self):
    """Sync calendar events for all users with Google OAuth"""
    try:
        logger.info("Starting calendar sync for all users")
        
        # Run sync function
        result = _sync_all_users_calendar_sync()
        
        logger.info(f"All users calendar sync completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"All users calendar sync failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_all_users_calendar_sync() -> Dict[str, Any]:
    """Sync implementation of syncing calendar for all users"""
    with SyncSessionLocal() as session:
        # Get all users with Google OAuth tokens
        result = session.execute(
            select(User).where(User.google_access_token.is_not(None))
        )
        users = result.scalars().all()
        
        sync_results = []
        
        for user in users:
            try:
                # Schedule individual sync
                sync_result = sync_calendar_events.delay(user.id)
                sync_results.append({
                    "user_id": user.id,
                    "task_id": sync_result.id,
                    "status": "scheduled"
                })
                
            except Exception as e:
                logger.error(f"Failed to schedule calendar sync for user {user.id}: {str(e)}")
                sync_results.append({
                    "user_id": user.id,
                    "status": "failed",
                    "error": str(e)
                })
        
        return {
            "total_users": len(users),
            "scheduled_syncs": len([r for r in sync_results if r["status"] == "scheduled"]),
            "failed_syncs": len([r for r in sync_results if r["status"] == "failed"]),
            "sync_results": sync_results,
            "synced_at": datetime.utcnow().isoformat()
        }

def update_user_google_tokens(user_id: str, access_token: str, refresh_token: str, expires_at: datetime):
    """Update user's Google tokens in database"""
    try:
        with SyncSessionLocal() as session:
            result = session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            
            if user:
                user.google_access_token = access_token
                if refresh_token:  # Only update if we have a new refresh token
                    user.google_refresh_token = refresh_token
                user.google_token_expires_at = expires_at
                user.updated_at = datetime.utcnow()
                
                session.commit()
                logger.info(f"Successfully updated Google tokens for user {user_id}")
            else:
                logger.error(f"User {user_id} not found when updating Google tokens")
    except Exception as e:
        logger.error(f"Failed to update Google tokens for user {user_id}: {str(e)}")
        raise 