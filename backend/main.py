from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import structlog
from typing import Optional

from config import get_settings
from database import init_db, get_db
from auth import get_current_user
from routers import auth, chat, integrations, proactive

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting Financial Agent API")
    
    # Initialize database first
    await init_db()
    
    # Run database migrations IMMEDIATELY after database init and BEFORE any services
    try:
        from database import migrate_add_thank_you_email_fields
        logger.info("🔄 Running database migrations...")
        await migrate_add_thank_you_email_fields()
        logger.info("✅ Database migrations completed successfully")
    except Exception as e:
        logger.error(f"❌ Database migration failed: {str(e)}")
        # Don't start the app if migrations fail
        raise e
    
    # Start Gmail polling service AFTER migrations are complete
    try:
        from services.gmail_polling_service import gmail_polling_service
        import asyncio
        
        # Start polling service in background
        polling_task = asyncio.create_task(gmail_polling_service.start_polling())
        logger.info("🚀 Gmail polling service started")
        
        # Store task for cleanup
        app.state.polling_task = polling_task
        
    except Exception as e:
        logger.error(f"❌ Failed to start Gmail polling service: {str(e)}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Financial Agent API")
    
    # Stop Gmail polling service
    try:
        if hasattr(app.state, 'polling_task'):
            await gmail_polling_service.stop_polling()
            app.state.polling_task.cancel()
            logger.info("🛑 Gmail polling service stopped")
    except Exception as e:
        logger.error(f"❌ Error stopping Gmail polling service: {str(e)}")

# Initialize FastAPI app
app = FastAPI(
    title="Financial Agent API",
    description="AI Agent for Financial Advisors with Gmail, Calendar, and HubSpot integration",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["authentication"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
app.include_router(proactive.router, prefix="/api", tags=["proactive"])

@app.get("/")
async def root():
    return {"message": "Financial Agent API", "status": "running"}

@app.get("/health")
async def health_check():
    """Health check endpoint with service status"""
    health_status = {
        "status": "healthy",
        "message": "API is running",
        "services": {
            "database": "unknown",
            "redis": "unknown"
        }
    }
    
    # Check database connection
    try:
        from database import AsyncSessionLocal
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        health_status["services"]["database"] = "healthy"
    except Exception as e:
        health_status["services"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis connection
    try:
        import redis
        r = redis.from_url(get_settings().redis_url)
        r.ping()
        health_status["services"]["redis"] = "healthy"
    except Exception as e:
        health_status["services"]["redis"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    return health_status

# Protected route example
@app.get("/me")
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    return current_user

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 