from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
import structlog
from typing import Optional

from config import get_settings
from database import init_db, get_db
from auth import get_current_user
from routers import auth, chat, integrations

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
    await init_db()
    yield
    # Shutdown
    logger.info("Shutting down Financial Agent API")

# Initialize FastAPI app
app = FastAPI(
    title="Financial Agent API",
    description="AI Agent for Financial Advisors with Gmail, Calendar, and HubSpot integration",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["authentication"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(integrations.router, prefix="/integrations", tags=["integrations"])

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