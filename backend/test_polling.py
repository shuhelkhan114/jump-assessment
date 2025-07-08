#!/usr/bin/env python3
"""
Test script for Gmail polling service
"""
import asyncio
import structlog
from services.gmail_polling_service import gmail_polling_service

logger = structlog.get_logger()

async def test_polling_service():
    """Test the Gmail polling service"""
    try:
        logger.info("🧪 Testing Gmail polling service...")
        
        # Start the polling service
        logger.info("🚀 Starting polling service...")
        
        # Run for a short time to test
        polling_task = asyncio.create_task(gmail_polling_service.start_polling())
        
        # Let it run for 60 seconds
        await asyncio.sleep(60)
        
        # Stop the service
        logger.info("🛑 Stopping polling service...")
        await gmail_polling_service.stop_polling()
        polling_task.cancel()
        
        logger.info("✅ Polling service test completed")
        
    except Exception as e:
        logger.error(f"❌ Polling service test failed: {str(e)}")
        raise

if __name__ == "__main__":
    print("🧪 Gmail Polling Service Test")
    print("=" * 40)
    
    # Run the test
    asyncio.run(test_polling_service()) 