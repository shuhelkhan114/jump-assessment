#!/usr/bin/env python3
"""
Migration script to add thank you email tracking fields to HubSpot contacts
"""
import asyncio
import sys
import structlog
from database import migrate_add_thank_you_email_fields

logger = structlog.get_logger()

async def main():
    """Run the migration"""
    try:
        logger.info("🚀 Starting migration: Adding thank you email fields to HubSpot contacts")
        await migrate_add_thank_you_email_fields()
        logger.info("✅ Migration completed successfully!")
        return 0
    except Exception as e:
        logger.error(f"❌ Migration failed: {str(e)}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 