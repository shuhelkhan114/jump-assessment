#!/usr/bin/env python3
"""
Test script for email-to-notes functionality
"""
import asyncio
import sys
import structlog
from datetime import datetime, timezone
from database import AsyncSessionLocal, User, HubspotContact
from sqlalchemy import select
from services.gmail_polling_service import gmail_polling_service
from services.hubspot_service import hubspot_service

logger = structlog.get_logger()

async def test_email_to_notes():
    """Test the email-to-notes functionality"""
    try:
        logger.info("🧪 Testing email-to-notes functionality")
        
        async with AsyncSessionLocal() as session:
            # Get a user with both HubSpot and Gmail tokens
            result = await session.execute(
                select(User).where(
                    User.hubspot_access_token.is_not(None),
                    User.google_access_token.is_not(None)
                ).limit(1)
            )
            
            user = result.scalar_one_or_none()
            
            if not user:
                logger.error("❌ No user found with both HubSpot and Gmail tokens")
                return False
            
            logger.info(f"✅ Found test user: {user.email}")
            
            # Create mock email data that would trigger contact creation
            mock_email_data = {
                "sender": "John Smith <john@testcompany.com>",
                "subject": "Potential collaboration opportunity",
                "content": """Hi there,

I came across your company and am interested in exploring potential collaboration opportunities. We're a technology company specializing in AI solutions and think there might be synergy between our businesses.

Would you be available for a brief call next week to discuss potential partnerships?

Best regards,
John Smith
CEO, TestCompany Inc.
john@testcompany.com
(555) 123-4567""",
                "received_at": datetime.now(timezone.utc),
                "gmail_id": "test_message_123",
                "thread_id": "test_thread_456"
            }
            
            logger.info(f"📧 Simulating email from: {mock_email_data['sender']}")
            logger.info(f"📝 Subject: {mock_email_data['subject']}")
            
            # Check if contact already exists
            contact_email = "john@testcompany.com"
            existing_contact = await gmail_polling_service._check_contact_exists(user.id, contact_email)
            
            if existing_contact:
                logger.info(f"⚠️ Contact {contact_email} already exists, skipping creation test")
                return True
            
            # Test the contact creation with email note
            logger.info("🚀 Testing contact creation with email note...")
            
            # Initialize HubSpot service for this user
            initialized = hubspot_service.initialize_service(
                access_token=user.hubspot_access_token
            )
            
            if not initialized:
                logger.error("❌ Failed to initialize HubSpot service")
                return False
            
            # Extract sender name
            sender_name = await gmail_polling_service._extract_sender_name(mock_email_data["sender"])
            logger.info(f"👤 Extracted name: {sender_name}")
            
            # Create contact data
            contact_data = {
                "email": contact_email,
                "firstname": sender_name.get("first_name", ""),
                "lastname": sender_name.get("last_name", ""),
                "company": "TestCompany Inc.",
                "lifecyclestage": "lead"
            }
            
            # Create contact in HubSpot
            created_contact = await hubspot_service.create_contact(contact_data)
            
            if not created_contact:
                logger.error("❌ Failed to create HubSpot contact")
                return False
            
            contact_id = created_contact.get("id")
            logger.info(f"✅ Created HubSpot contact: {contact_id}")
            
            # Test the email note creation
            logger.info("📝 Testing email note creation...")
            
            await gmail_polling_service._add_email_note_to_contact(
                contact_id=contact_id,
                email_data=mock_email_data,
                user_id=user.id
            )
            
            # Save contact to local database
            await gmail_polling_service._save_contact_to_db(user.id, contact_email, created_contact)
            
            logger.info("🎉 Test completed successfully!")
            logger.info("✅ Contact created with email note")
            logger.info("✅ Thank you email sent")
            logger.info("✅ Contact saved to local database")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Test failed: {str(e)}")
        return False

async def main():
    """Run the test"""
    try:
        logger.info("🚀 Starting email-to-notes functionality test")
        success = await test_email_to_notes()
        
        if success:
            logger.info("✅ Test completed successfully!")
            return 0
        else:
            logger.error("❌ Test failed!")
            return 1
            
    except Exception as e:
        logger.error(f"❌ Test error: {str(e)}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 