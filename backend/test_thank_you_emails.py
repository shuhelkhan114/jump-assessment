#!/usr/bin/env python3
"""
Test script for thank you email functionality
"""
import asyncio
import sys
import structlog
from database import AsyncSessionLocal, User, HubspotContact
from sqlalchemy import select
from tasks.hubspot_tasks import send_thank_you_emails_to_new_contacts

logger = structlog.get_logger()

async def test_thank_you_emails():
    """Test the thank you email functionality"""
    try:
        logger.info("🧪 Testing thank you email functionality")
        
        async with AsyncSessionLocal() as session:
            # Get a user with both HubSpot and Gmail tokens
            result = await session.execute(
                select(User).where(
                    User.hubspot_access_token.is_not(None),
                    User.google_access_token.is_not(None)
                )
            )
            users = result.scalars().all()
            
            if not users:
                logger.error("❌ No users found with both HubSpot and Gmail tokens")
                return False
            
            user = users[0]
            logger.info(f"📧 Testing with user: {user.email}")
            
            # Check for contacts that haven't received thank you emails
            contacts_result = await session.execute(
                select(HubspotContact).where(
                    HubspotContact.user_id == user.id,
                    HubspotContact.thank_you_email_sent == False
                ).limit(5)
            )
            
            contacts = contacts_result.scalars().all()
            
            logger.info(f"📧 Found {len(contacts)} contacts without thank you emails")
            
            if contacts:
                for contact in contacts:
                    logger.info(f"  - {contact.firstname} {contact.lastname} ({contact.email})")
            
            # Test the Celery task
            logger.info("🔄 Triggering thank you email task...")
            result = send_thank_you_emails_to_new_contacts.delay(user.id)
            
            logger.info(f"✅ Task triggered with ID: {result.id}")
            
            return True
            
    except Exception as e:
        logger.error(f"❌ Test failed: {str(e)}")
        return False

async def check_database_schema():
    """Check if the database schema has the required fields"""
    try:
        logger.info("🔍 Checking database schema for thank you email fields")
        
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            
            # Check if the new columns exist
            result = await session.execute(text("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'hubspot_contacts' 
                AND column_name IN ('thank_you_email_sent', 'thank_you_email_sent_at')
                ORDER BY column_name
            """))
            
            columns = [row[0] for row in result.fetchall()]
            
            if 'thank_you_email_sent' in columns and 'thank_you_email_sent_at' in columns:
                logger.info("✅ Database schema is up-to-date")
                return True
            else:
                logger.error(f"❌ Missing columns. Found: {columns}")
                return False
                
    except Exception as e:
        logger.error(f"❌ Schema check failed: {str(e)}")
        return False

async def test_contact_creation_flow():
    """Test the new contact creation and thank you email flow"""
    try:
        logger.info("🔄 Testing contact creation flow...")
        
        async with AsyncSessionLocal() as session:
            # Get a user for testing
            result = await session.execute(
                select(User).where(
                    User.hubspot_access_token.is_not(None),
                    User.google_access_token.is_not(None)
                )
            )
            user = result.scalar_one_or_none()
            
            if not user:
                logger.error("❌ No user found with required tokens")
                return False
            
            # Create a test contact manually (this would normally happen via Gmail polling)
            from services.gmail_polling_service import gmail_polling_service
            
            # Mock email data
            test_email_data = {
                "sender": "Test User <testuser@example.com>",
                "subject": "Test Email",
                "content": "This is a test email"
            }
            
            # Mock HubSpot contact data
            test_hubspot_contact = {
                "id": "test_contact_123",
                "properties": {
                    "firstname": "Test",
                    "lastname": "User",
                    "email": "testuser@example.com",
                    "lifecyclestage": "lead"
                }
            }
            
            # Test the save contact and thank you email flow
            await gmail_polling_service._save_contact_to_db(
                user.id, 
                "testuser@example.com", 
                test_hubspot_contact
            )
            
            logger.info("✅ Contact creation flow test completed")
            return True
            
    except Exception as e:
        logger.error(f"❌ Contact creation flow test failed: {str(e)}")
        return False

async def main():
    """Run all tests"""
    try:
        logger.info("🚀 Starting thank you email tests")
        
        # Test 1: Check database schema
        schema_ok = await check_database_schema()
        if not schema_ok:
            logger.error("❌ Database schema check failed")
            return 1
        
        # Test 2: Test thank you email task
        task_ok = await test_thank_you_emails()
        if not task_ok:
            logger.error("❌ Thank you email task test failed")
            return 1
        
        # Test 3: Test contact creation flow
        flow_ok = await test_contact_creation_flow()
        if not flow_ok:
            logger.error("❌ Contact creation flow test failed")
            return 1
        
        logger.info("✅ All tests completed successfully!")
        return 0
        
    except Exception as e:
        logger.error(f"❌ Tests failed: {str(e)}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 