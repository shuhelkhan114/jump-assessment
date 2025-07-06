"""
Celery tasks for Gmail data synchronization and processing
"""
from celery import Celery
from typing import Dict, Any, List
import asyncio
import json
import structlog
from datetime import datetime
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from database import User, Email
from services.gmail_service import gmail_service
from services.openai_service import openai_service
from celery_app import celery_app
from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Create synchronous database engine for Celery tasks
sync_engine = create_engine(settings.database_url, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine)

@celery_app.task(bind=True, max_retries=3)
def sync_gmail_emails(self, user_id: str, days_back: int = 30):
    """Sync Gmail emails for a user"""
    try:
        logger.info(f"Starting Gmail sync for user {user_id}")
        
        # Run sync function
        result = _sync_gmail_emails_sync(user_id, days_back)
        
        logger.info(f"Gmail sync completed for user {user_id}: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Gmail sync failed for user {user_id}: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_gmail_emails_sync(user_id: str, days_back: int = 30) -> Dict[str, Any]:
    """Sync implementation of Gmail sync"""
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
        
        # Initialize Gmail service
        if not gmail_service.initialize_service(
            user.google_access_token,
            user.google_refresh_token or ""
        ):
            raise Exception("Failed to initialize Gmail service")
        
        # Get existing Gmail IDs to avoid duplicates
        existing_result = session.execute(
            select(Email.gmail_id).where(Email.user_id == user_id)
        )
        existing_gmail_ids = {row[0] for row in existing_result.fetchall()}
        
        # Fetch messages from Gmail (using asyncio.run for the async service call)
        messages = asyncio.run(gmail_service.list_messages(days_back=days_back))
        
        # Also fetch the latest 200 messages without date filtering to ensure we don't miss any
        if days_back <= 7:  # Only for recent syncs to avoid too much processing
            latest_messages = asyncio.run(gmail_service.list_latest_messages(max_results=200))
            
            # Combine and deduplicate messages
            all_message_ids = {msg['id'] for msg in messages}
            for msg in latest_messages:
                if msg['id'] not in all_message_ids:
                    messages.append(msg)
            
            logger.info(f"Combined sync: {len(messages)} total messages (including latest without date filter)")
        
        new_emails = []
        processed_count = 0
        
        for message in messages:
            gmail_id = message['id']
            
            # Skip if already processed
            if gmail_id in existing_gmail_ids:
                continue
            
            try:
                # Get message content (using asyncio.run for the async service call)
                email_data = asyncio.run(gmail_service.get_message_content(gmail_id))
                
                # Create email record
                email = Email(
                    user_id=user_id,
                    gmail_id=gmail_id,
                    thread_id=email_data.get('thread_id'),
                    subject=email_data.get('subject'),
                    content=email_data.get('content'),
                    sender=email_data.get('sender'),
                    recipient=email_data.get('recipient'),
                    received_at=email_data.get('received_at'),
                    is_read=email_data.get('is_read', False),
                    labels=json.dumps(email_data.get('labels', []))
                )
                
                session.add(email)
                new_emails.append(email)
                processed_count += 1
                
                # Commit in batches
                if processed_count % 10 == 0:
                    session.commit()
                    logger.info(f"Processed {processed_count} emails for user {user_id}")
                
            except Exception as e:
                logger.error(f"Failed to process message {gmail_id}: {str(e)}")
                continue
        
        # Final commit
        session.commit()
        
        # Schedule embedding generation for new emails
        if new_emails:
            generate_email_embeddings.delay(user_id, [email.id for email in new_emails])
        
        return {
            "user_id": user_id,
            "total_messages": len(messages),
            "new_emails": len(new_emails),
            "processed_count": processed_count,
            "synced_at": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True, max_retries=3)
def generate_email_embeddings(self, user_id: str, email_ids: List[str]):
    """Generate embeddings for email content"""
    try:
        logger.info(f"Starting embedding generation for {len(email_ids)} emails")
        
        # Run sync function
        result = _generate_email_embeddings_sync(user_id, email_ids)
        
        logger.info(f"Embedding generation completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Embedding generation failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _generate_email_embeddings_sync(user_id: str, email_ids: List[str]) -> Dict[str, Any]:
    """Sync implementation of embedding generation"""
    with SyncSessionLocal() as session:
        # Get emails without embeddings
        result = session.execute(
            select(Email).where(
                Email.user_id == user_id,
                Email.id.in_(email_ids),
                Email.embedding.is_(None)
            )
        )
        emails = result.scalars().all()
        
        processed_count = 0
        
        for email in emails:
            try:
                # Create text for embedding
                email_text = _create_email_text_for_embedding(email)
                
                # Generate embedding (using asyncio.run for the async service call)
                embedding = asyncio.run(openai_service.generate_embedding(email_text))
                
                if embedding:
                    # Update email with embedding
                    email.embedding = embedding
                    processed_count += 1
                    
                    # Commit in batches
                    if processed_count % 5 == 0:
                        session.commit()
                        logger.info(f"Generated embeddings for {processed_count} emails")
                
            except Exception as e:
                logger.error(f"Failed to generate embedding for email {email.id}: {str(e)}")
                continue
        
        # Final commit
        session.commit()
        
        return {
            "user_id": user_id,
            "total_emails": len(emails),
            "processed_count": processed_count,
            "generated_at": datetime.utcnow().isoformat()
        }

def _create_email_text_for_embedding(email: Email) -> str:
    """Create text representation of email for embedding"""
    parts = []
    
    # Add subject
    if email.subject:
        parts.append(f"Subject: {email.subject}")
    
    # Add sender
    if email.sender:
        parts.append(f"From: {email.sender}")
    
    # Add content
    if email.content:
        # Truncate very long emails
        content = email.content[:2000] if len(email.content) > 2000 else email.content
        parts.append(f"Content: {content}")
    
    # Add date context
    if email.received_at:
        parts.append(f"Date: {email.received_at.strftime('%Y-%m-%d %H:%M')}")
    
    return "\n".join(parts)

@celery_app.task(bind=True, max_retries=3)
def sync_all_users_gmail(self):
    """Sync Gmail for all users with Google OAuth"""
    try:
        logger.info("Starting Gmail sync for all users")
        
        # Run sync function
        result = _sync_all_users_gmail_sync()
        
        logger.info(f"All users Gmail sync completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"All users Gmail sync failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_all_users_gmail_sync() -> Dict[str, Any]:
    """Sync implementation of syncing all users"""
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
                sync_result = sync_gmail_emails.delay(user.id)
                sync_results.append({
                    "user_id": user.id,
                    "task_id": sync_result.id,
                    "status": "scheduled"
                })
                
            except Exception as e:
                logger.error(f"Failed to schedule sync for user {user.id}: {str(e)}")
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

@celery_app.task
def send_email_task(user_id: str, to: str, subject: str, body: str, cc: str = None):
    """Send email via Gmail API"""
    try:
        logger.info(f"Sending email for user {user_id} to {to}")
        
        # Run sync function
        result = _send_email_sync(user_id, to, subject, body, cc)
        
        logger.info(f"Email sent successfully: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Email sending failed: {str(e)}")
        raise e

def _send_email_sync(user_id: str, to: str, subject: str, body: str, cc: str = None) -> Dict[str, Any]:
    """Sync implementation of email sending"""
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
        
        # Initialize Gmail service
        if not gmail_service.initialize_service(
            user.google_access_token,
            user.google_refresh_token or ""
        ):
            raise Exception("Failed to initialize Gmail service")
        
        # Send email (using asyncio.run for the async service call)
        result = asyncio.run(gmail_service.send_email(to, subject, body, cc))
        
        return {
            "user_id": user_id,
            "to": to,
            "subject": subject,
            "message_id": result.get('id'),
            "sent_at": datetime.utcnow().isoformat()
        } 