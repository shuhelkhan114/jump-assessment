"""
Gmail Polling Service for checking new emails and auto-creating HubSpot contacts
"""
import asyncio
import structlog
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import re
import inspect
from database import AsyncSessionLocal, Email, HubspotContact, get_user_by_id
from services.gmail_service import gmail_service
from services.hubspot_service import hubspot_service

logger = structlog.get_logger()

class GmailPollingService:
    """Service for polling Gmail and auto-creating HubSpot contacts"""
    
    def __init__(self):
        self.polling_interval = 30  # seconds - more conservative for Gmail API
        self.is_running = False
        self.last_check_times = {}  # Track last check time per user
        self.rate_limit_delay = 2  # seconds between API calls to respect rate limits
        self.max_emails_per_poll = 20  # Limit emails per poll to avoid quota issues
        
    async def start_polling(self):
        """Start the Gmail polling service"""
        if self.is_running:
            logger.warning("Gmail polling service is already running")
            return
        
        self.is_running = True
        logger.info("🚀 Starting Gmail polling service")
        
        try:
            while self.is_running:
                await self._poll_all_users()
                await asyncio.sleep(self.polling_interval)
        except Exception as e:
            logger.error(f"❌ Gmail polling service error: {str(e)}")
            self.is_running = False
            raise
    
    async def stop_polling(self):
        """Stop the Gmail polling service"""
        self.is_running = False
        logger.info("🛑 Stopping Gmail polling service")
    
    async def _poll_all_users(self):
        """Poll Gmail for all users with Gmail integration"""
        try:
            # Get all users with Gmail access tokens
            async with AsyncSessionLocal() as session:
                from database import User
                from sqlalchemy import select
                
                result = await session.execute(
                    select(User).where(User.google_access_token.isnot(None))
                )
                users = result.scalars().all()
                
                logger.info(f"📧 Polling Gmail for {len(users)} users")
                
                for user in users:
                    try:
                        await self._poll_user_emails(user)
                        # Rate limiting: wait between users
                        await asyncio.sleep(self.rate_limit_delay)
                    except Exception as e:
                        user_email = getattr(user, 'email', 'unknown') if user else 'unknown'
                        logger.error(f"❌ Error polling emails for user {user_email}: {str(e)}")
                        continue
                        
        except Exception as e:
            logger.error(f"❌ Error in _poll_all_users: {str(e)}")
    
    async def _poll_user_emails(self, user):
        """Poll Gmail for a specific user"""
        try:
            user_id = user.id
            
            # Get user email robustly
            user_email = getattr(user, 'email', None)
            if inspect.iscoroutine(user_email):
                user_email = await user_email
            if not user_email:
                logger.warning(f"⚠️ User {user_id} has no email address")
                return
            
            # Check if we should poll this user (rate limiting)
            last_check = self.last_check_times.get(user_id)
            if last_check and (datetime.utcnow() - last_check).seconds < self.polling_interval:
                return
            
            logger.info(f"📧 Polling Gmail for user: {user_email}")
            
            # Initialize Gmail service for this user
            initialized = gmail_service.initialize_service(
                access_token=user.google_access_token,
                refresh_token=user.google_refresh_token or "",
                user_id=user_id
            )
            
            if not initialized:
                logger.error(f"❌ Failed to initialize Gmail service for user {user_email}")
                return
            
            # Get the last check time for this user
            last_check_time = await self._get_last_email_check_time(user_id)
            
            # Get recent emails since last check
            since_timestamp = last_check_time or (datetime.utcnow() - timedelta(hours=1))
            
            try:
                emails = await gmail_service.get_recent_emails(user_id, since_timestamp, max_results=self.max_emails_per_poll)
            except Exception as api_error:
                error_str = str(api_error).lower()
                
                # Handle rate limit and quota errors
                if "quota" in error_str or "rate" in error_str or "429" in error_str:
                    logger.warning(f"⚠️ Gmail API rate limit/quota exceeded for user {user_email}, backing off...")
                    # Increase delay for this user to avoid hitting limits
                    self.last_check_times[user_id] = datetime.utcnow() + timedelta(minutes=5)
                    return
                elif "unauthorized" in error_str or "invalid_grant" in error_str:
                    logger.error(f"❌ Gmail authentication failed for user {user_email} - token may be expired")
                    return
                else:
                    logger.error(f"❌ Gmail API error for user {user_email}: {str(api_error)}")
                    return
            
            if not emails:
                logger.info(f"📧 No new emails for user {user_email}")
                self.last_check_times[user_id] = datetime.utcnow()
                return
            
            logger.info(f"📧 Found {len(emails)} new emails for user {user_email}")
            
            # Process each email
            for email_data in emails:
                await self._process_email(user, email_data)
                # Rate limiting: wait between emails
                await asyncio.sleep(self.rate_limit_delay)
            
            # Update last check time
            self.last_check_times[user_id] = datetime.utcnow()
            
        except Exception as e:
            user_email = getattr(user, 'email', 'unknown') if user else 'unknown'
            if inspect.iscoroutine(user_email):
                try:
                    user_email = await user_email
                except:
                    user_email = 'unknown'
            logger.error(f"❌ Error polling emails for user {user_email}: {str(e)}")
    
    async def _process_email(self, user, email_data):
        """Process a single email and create HubSpot contact if sender is unknown"""
        try:
            sender_email = email_data.get("sender", "")
            subject = email_data.get("subject", "")
            
            if not sender_email or "@" not in sender_email:
                return
            
            # Extract clean email address from sender
            clean_email = await self._extract_email_address(sender_email)
            if not clean_email:
                return
            
            # Get user email robustly
            user_email = getattr(user, 'email', None)
            if inspect.iscoroutine(user_email):
                user_email = await user_email
            if not user_email:
                logger.warning(f"⚠️ User {getattr(user, 'id', 'unknown')} has no email address")
                return
            
            # Skip if sender is the user themselves
            if clean_email.lower() == user_email.lower():
                return
            
            # Check if this email already exists in HubSpot contacts
            contact_exists = await self._check_contact_exists(user.id, clean_email)
            
            if contact_exists:
                logger.info(f"📧 Contact {clean_email} already exists in HubSpot for user {user_email}")
                return
            
            # Create HubSpot contact for unknown sender
            await self._create_hubspot_contact(user, clean_email, email_data)
            
        except Exception as e:
            logger.error(f"❌ Error processing email: {str(e)}")
    
    async def _extract_email_address(self, sender_string: str) -> Optional[str]:
        """Extract clean email address from sender string"""
        try:
            # Handle formats like "Name <email@domain.com>" or just "email@domain.com"
            email_pattern = r'[\w\.-]+@[\w\.-]+\.\w+'
            match = re.search(email_pattern, sender_string)
            if match:
                return match.group(0).lower()
            return None
        except Exception as e:
            logger.error(f"❌ Error extracting email address: {str(e)}")
            return None
    
    async def _check_contact_exists(self, user_id: str, email: str) -> bool:
        """Check if a contact already exists in HubSpot for this user"""
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select
                
                result = await session.execute(
                    select(HubspotContact).where(
                        HubspotContact.user_id == user_id,
                        HubspotContact.email == email
                    )
                )
                existing_contact = result.scalar_one_or_none()
                
                return existing_contact is not None
                
        except Exception as e:
            logger.error(f"❌ Error checking contact existence: {str(e)}")
            return False
    
    async def _create_hubspot_contact(self, user, email: str, email_data: Dict[str, Any]):
        """Create a new HubSpot contact for an unknown sender"""
        try:
            # Get user email robustly
            user_email = getattr(user, 'email', 'unknown')
            if inspect.iscoroutine(user_email):
                user_email = await user_email
            
            logger.info(f"📧 Creating HubSpot contact for {email} (user: {user_email})")
            
            # Initialize HubSpot service for this user
            if not user.hubspot_access_token:
                logger.warning(f"⚠️ User {user_email} has no HubSpot access token - cannot create contact")
                return
            
            initialized = hubspot_service.initialize_service(
                access_token=user.hubspot_access_token
            )
            
            if not initialized:
                logger.error(f"❌ Failed to initialize HubSpot service for user {user_email}")
                return
            
            # Extract sender name from email data
            sender_name = await self._extract_sender_name(email_data.get("sender", ""))
            
            # Create contact in HubSpot
            contact_data = {
                "email": email,
                "firstname": sender_name.get("first_name", ""),
                "lastname": sender_name.get("last_name", ""),
                "company": "",  # Could be extracted from email domain or content
                "lifecyclestage": "lead"
            }
            
            created_contact = await hubspot_service.create_contact(contact_data)
            
            if created_contact:
                logger.info(f"✅ Successfully created HubSpot contact for {email}")
                
                # Add email content as note to the contact
                await self._add_email_note_to_contact(
                    contact_id=created_contact.get("id"),
                    email_data=email_data,
                    user_id=user.id
                )
                
                # Save contact to local database
                await self._save_contact_to_db(user.id, email, created_contact)
            else:
                logger.error(f"❌ Failed to create HubSpot contact for {email}")
                
        except Exception as e:
            logger.error(f"❌ Error creating HubSpot contact for {email}: {str(e)}")
    
    async def _extract_sender_name(self, sender_string: str) -> Dict[str, str]:
        """Extract sender name from sender string"""
        try:
            # Handle format "Name <email@domain.com>"
            if "<" in sender_string and ">" in sender_string:
                name_part = sender_string.split("<")[0].strip()
                if name_part:
                    # Split name into first and last
                    name_parts = name_part.split()
                    if len(name_parts) >= 2:
                        return {
                            "first_name": name_parts[0],
                            "last_name": " ".join(name_parts[1:])
                        }
                    else:
                        return {
                            "first_name": name_parts[0],
                            "last_name": ""
                        }
            
            # If no name found, return empty
            return {"first_name": "", "last_name": ""}
            
        except Exception as e:
            logger.error(f"❌ Error extracting sender name: {str(e)}")
            return {"first_name": "", "last_name": ""}
    
    async def _add_email_note_to_contact(self, contact_id: str, email_data: Dict[str, Any], user_id: str):
        """Add email content as a note to the HubSpot contact"""
        try:
            # Extract email content for the note
            subject = email_data.get("subject", "No Subject")
            content = email_data.get("content", "")
            sender = email_data.get("sender", "Unknown")
            received_at = email_data.get("received_at", datetime.utcnow())
            
            # Format the received date nicely
            if isinstance(received_at, str):
                received_at = datetime.fromisoformat(received_at.replace('Z', '+00:00'))
            elif received_at is None:
                received_at = datetime.utcnow()
            
            formatted_date = received_at.strftime("%B %d, %Y at %I:%M %p")
            
            # Create formatted note content
            note_content = f"""📧 Initial Contact via Email
Received: {formatted_date}
From: {sender}
Subject: {subject}

Email Content:
{content[:1000]}{"..." if len(content) > 1000 else ""}

This contact was automatically created from an incoming email."""
            
            # Create the note using HubSpot engagements API
            note_data = {
                "engagement": {
                    "type": "NOTE"
                },
                "metadata": {
                    "body": note_content
                },
                "associations": {
                    "contactIds": [contact_id]
                }
            }
            
            result = await hubspot_service.create_engagement(note_data)
            
            if result and result.get("_status") == "created":
                logger.info(f"✅ Added email note to HubSpot contact {contact_id}")
            else:
                logger.warning(f"⚠️ Note creation result unclear for contact {contact_id}: {result}")
                
        except Exception as e:
            logger.error(f"❌ Error adding email note to contact {contact_id}: {str(e)}")
            # Don't fail the whole contact creation process if note fails
            pass
    
    async def _save_contact_to_db(self, user_id: str, email: str, hubspot_contact: Dict[str, Any]):
        """Save the created contact to local database"""
        try:
            async with AsyncSessionLocal() as session:
                try:
                    # Try to create contact with thank you email fields
                    new_contact = HubspotContact(
                        id=str(hubspot_contact.get("id")),
                        user_id=user_id,
                        hubspot_id=str(hubspot_contact.get("id")),
                        email=email,
                        firstname=hubspot_contact.get("properties", {}).get("firstname", ""),
                        lastname=hubspot_contact.get("properties", {}).get("lastname", ""),
                        company=hubspot_contact.get("properties", {}).get("company", ""),
                        phone=hubspot_contact.get("properties", {}).get("phone", ""),
                        lifecyclestage=hubspot_contact.get("properties", {}).get("lifecyclestage", ""),
                        lead_status=hubspot_contact.get("properties", {}).get("hs_lead_status", ""),
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                        # Thank you email fields - set defaults
                        thank_you_email_sent=False,
                        thank_you_email_sent_at=None
                    )
                    
                    session.add(new_contact)
                    await session.commit()
                    
                    logger.info(f"✅ Saved contact {email} to local database with thank you email fields")
                    
                    # Send thank you email to the new contact
                    await self._send_thank_you_email(user_id, email, new_contact)
                    
                except Exception as db_error:
                    # Check if this is a missing column error
                    if "thank_you_email_sent" in str(db_error) and "does not exist" in str(db_error):
                        logger.warning(f"⚠️ Thank you email fields not yet migrated, creating contact without them")
                        await session.rollback()
                        
                        # Create contact without thank you email fields
                        fallback_contact = HubspotContact(
                            id=str(hubspot_contact.get("id")),
                            user_id=user_id,
                            hubspot_id=str(hubspot_contact.get("id")),
                            email=email,
                            firstname=hubspot_contact.get("properties", {}).get("firstname", ""),
                            lastname=hubspot_contact.get("properties", {}).get("lastname", ""),
                            company=hubspot_contact.get("properties", {}).get("company", ""),
                            phone=hubspot_contact.get("properties", {}).get("phone", ""),
                            lifecyclestage=hubspot_contact.get("properties", {}).get("lifecyclestage", ""),
                            lead_status=hubspot_contact.get("properties", {}).get("hs_lead_status", ""),
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                        
                        session.add(fallback_contact)
                        await session.commit()
                        
                        logger.info(f"✅ Saved contact {email} to local database (without thank you email fields)")
                        
                        # Send thank you email anyway (we'll track it separately if needed)
                        await self._send_thank_you_email(user_id, email, fallback_contact)
                    else:
                        # Re-raise other database errors
                        raise db_error
                
        except Exception as e:
            logger.error(f"❌ Error saving contact to database: {str(e)}")
    
    async def _send_thank_you_email(self, user_id: str, contact_email: str, contact: HubspotContact):
        """Send thank you email to new contact"""
        try:
            logger.info(f"📧 Sending thank you email to {contact_email}")
            
            # Get contact name for personalization
            contact_name = f"{contact.firstname} {contact.lastname}".strip()
            if not contact_name:
                contact_name = contact_email.split('@')[0].title()  # Use email username as fallback
            
            # Create email content
            subject = "Thank you for being a customer"
            body = f"Hello {contact_name}, Thank you for being a customer."
            
            # Send email using Gmail service
            success = await gmail_service.send_email(
                to=contact_email,
                subject=subject,
                body=body
            )
            
            if success:
                logger.info(f"✅ Thank you email sent successfully to {contact_email}")
                
                # Update the contact to mark thank you email as sent
                await self._mark_thank_you_email_sent(contact.id)
            else:
                logger.error(f"❌ Failed to send thank you email to {contact_email}")
                
        except Exception as e:
            logger.error(f"❌ Error sending thank you email to {contact_email}: {str(e)}")
    
    async def _mark_thank_you_email_sent(self, contact_id: str):
        """Mark thank you email as sent for a contact"""
        try:
            async with AsyncSessionLocal() as session:
                # Try to update with thank you email fields
                try:
                    from sqlalchemy import update
                    
                    await session.execute(
                        update(HubspotContact)
                        .where(HubspotContact.id == contact_id)
                        .values(
                            thank_you_email_sent=True,
                            thank_you_email_sent_at=datetime.utcnow(),
                            updated_at=datetime.utcnow()
                        )
                    )
                    
                    await session.commit()
                    logger.info(f"✅ Marked thank you email as sent for contact {contact_id}")
                    
                except Exception as update_error:
                    # If update fails due to missing columns, just log it
                    if "thank_you_email_sent" in str(update_error):
                        logger.warning(f"⚠️ Could not update thank you email status (fields not migrated) for contact {contact_id}")
                    else:
                        logger.error(f"❌ Error updating thank you email status for contact {contact_id}: {str(update_error)}")
                        
        except Exception as e:
            logger.error(f"❌ Error marking thank you email as sent for contact {contact_id}: {str(e)}")
    
    async def _get_last_email_check_time(self, user_id: str) -> Optional[datetime]:
        """Get the last time we checked emails for this user"""
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import select, desc
                
                # Get the most recent email for this user
                result = await session.execute(
                    select(Email).where(Email.user_id == user_id).order_by(desc(Email.received_at)).limit(1)
                )
                latest_email = result.scalar_one_or_none()
                
                if latest_email:
                    return latest_email.received_at
                
                # If no emails found, return None (will check last hour)
                return None
                
        except Exception as e:
            logger.error(f"❌ Error getting last email check time: {str(e)}")
            return None

# Global polling service instance
gmail_polling_service = GmailPollingService() 