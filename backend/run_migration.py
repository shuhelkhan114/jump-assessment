#!/usr/bin/env python3
"""
Database migration script for adding contact_creation_context field
"""
import asyncio
import sys
import structlog
from sqlalchemy.exc import OperationalError
from database import AsyncSessionLocal, engine
from sqlalchemy import text

logger = structlog.get_logger()

async def add_contact_creation_context_field():
    """Add contact_creation_context field to hubspot_contacts table"""
    logger.info("Adding contact_creation_context field to hubspot_contacts table")
    
    try:
        async with AsyncSessionLocal() as session:
            # Check if column already exists
            result = await session.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'hubspot_contacts' 
                AND column_name = 'contact_creation_context';
            """))
            
            if result.scalar():
                logger.info("✅ contact_creation_context column already exists")
                return True
            
            # Add the column
            await session.execute(text("""
                ALTER TABLE hubspot_contacts 
                ADD COLUMN contact_creation_context VARCHAR DEFAULT 'customer';
            """))
            
            await session.commit()
            logger.info("✅ Successfully added contact_creation_context column")
            
            # Update existing contacts to have 'customer' context
            await session.execute(text("""
                UPDATE hubspot_contacts 
                SET contact_creation_context = 'customer' 
                WHERE contact_creation_context IS NULL;
            """))
            
            await session.commit()
            logger.info("✅ Updated existing contacts with 'customer' context")
            
            return True
            
    except OperationalError as e:
        if "already exists" in str(e).lower():
            logger.info("✅ contact_creation_context column already exists")
            return True
        else:
            logger.error(f"❌ Error adding contact_creation_context field: {str(e)}")
            return False
    except Exception as e:
        logger.error(f"❌ Unexpected error adding contact_creation_context field: {str(e)}")
        return False

async def main():
    """Run the migration"""
    logger.info("🔄 Starting contact creation context migration")
    
    success = await add_contact_creation_context_field()
    
    if success:
        logger.info("✅ Migration completed successfully")
        return 0
    else:
        logger.error("❌ Migration failed")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 