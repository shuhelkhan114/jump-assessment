from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, select
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from pgvector.sqlalchemy import Vector
from datetime import datetime
import uuid
from typing import Optional, List
import structlog

from config import get_settings

logger = structlog.get_logger()

# Database setup
settings = get_settings()

# Convert postgresql:// to postgresql+asyncpg:// for async
async_database_url = settings.database_url.replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(async_database_url, echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

# Database Models
class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=True)
    google_id = Column(String, unique=True, nullable=True)
    hubspot_id = Column(String, unique=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # OAuth tokens
    google_access_token = Column(Text, nullable=True)
    google_refresh_token = Column(Text, nullable=True)
    google_token_expires_at = Column(DateTime, nullable=True)
    
    hubspot_access_token = Column(Text, nullable=True)
    hubspot_refresh_token = Column(Text, nullable=True)
    hubspot_token_expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    emails = relationship("Email", back_populates="user")
    conversations = relationship("Conversation", back_populates="user")
    ongoing_instructions = relationship("OngoingInstruction", back_populates="user")
    hubspot_contacts = relationship("HubspotContact", back_populates="user")
    hubspot_deals = relationship("HubspotDeal", back_populates="user")
    hubspot_companies = relationship("HubspotCompany", back_populates="user")

class Email(Base):
    __tablename__ = "emails"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    gmail_id = Column(String, unique=True, nullable=False)
    thread_id = Column(String, nullable=True)
    subject = Column(Text, nullable=True)
    content = Column(Text, nullable=True)  # Renamed from body to content
    sender = Column(String, nullable=True)
    recipient = Column(String, nullable=True)
    received_at = Column(DateTime, nullable=True)  # Renamed from date to received_at
    is_read = Column(Boolean, default=False)
    labels = Column(Text, nullable=True)  # Store Gmail labels as JSON string
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Vector embedding for RAG
    embedding = Column(Vector(1536), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="emails")

class HubspotContact(Base):
    __tablename__ = "hubspot_contacts"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    hubspot_id = Column(String, nullable=False)
    firstname = Column(String, nullable=True)
    lastname = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    company = Column(String, nullable=True)
    jobtitle = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    lifecyclestage = Column(String, nullable=True)
    lead_status = Column(String, nullable=True)
    notes_last_contacted = Column(DateTime, nullable=True)
    notes_last_activity_date = Column(DateTime, nullable=True)
    num_notes = Column(Integer, nullable=True)
    properties = Column(Text, nullable=True)  # Store additional properties as JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Vector embedding for RAG
    embedding = Column(Vector(1536), nullable=True)
    
    # Relationships
    user = relationship("User")
    deals = relationship("HubspotDeal", back_populates="contact")

class HubspotDeal(Base):
    __tablename__ = "hubspot_deals"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    hubspot_id = Column(String, nullable=False)
    dealname = Column(String, nullable=True)
    amount = Column(Float, nullable=True)
    dealstage = Column(String, nullable=True)
    pipeline = Column(String, nullable=True)
    closedate = Column(DateTime, nullable=True)
    dealtype = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    notes_last_contacted = Column(DateTime, nullable=True)
    notes_last_activity_date = Column(DateTime, nullable=True)
    num_notes = Column(Integer, nullable=True)
    hubspot_owner_id = Column(String, nullable=True)
    contact_id = Column(String, ForeignKey("hubspot_contacts.id"), nullable=True)
    company_id = Column(String, ForeignKey("hubspot_companies.id"), nullable=True)
    properties = Column(Text, nullable=True)  # Store additional properties as JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Vector embedding for RAG
    embedding = Column(Vector(1536), nullable=True)
    
    # Relationships
    user = relationship("User")
    contact = relationship("HubspotContact", back_populates="deals")
    company = relationship("HubspotCompany", back_populates="deals")

class HubspotCompany(Base):
    __tablename__ = "hubspot_companies"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    hubspot_id = Column(String, nullable=False)
    name = Column(String, nullable=True)
    domain = Column(String, nullable=True)
    industry = Column(String, nullable=True)
    type = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    country = Column(String, nullable=True)
    num_employees = Column(Integer, nullable=True)
    annualrevenue = Column(Float, nullable=True)
    notes_last_contacted = Column(DateTime, nullable=True)
    notes_last_activity_date = Column(DateTime, nullable=True)
    num_notes = Column(Integer, nullable=True)
    properties = Column(Text, nullable=True)  # Store additional properties as JSON
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Vector embedding for RAG
    embedding = Column(Vector(1536), nullable=True)
    # Relationships
    user = relationship("User")
    deals = relationship("HubspotDeal", back_populates="company")

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    context_used = Column(Text, nullable=True)  # RAG context
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="conversations")

class OngoingInstruction(Base):
    __tablename__ = "ongoing_instructions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    instruction = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="ongoing_instructions")

class Task(Base):
    __tablename__ = "tasks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    description = Column(Text, nullable=False)
    status = Column(String, default="pending")  # pending, in_progress, completed, failed
    context = Column(Text, nullable=True)  # JSON context for resuming tasks
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User")

# Database connection management
async def init_db():
    """Initialize database connection and create tables"""
    try:
        from sqlalchemy import text
        
        # Create pgvector extension and tables
        async with engine.begin() as conn:
            # Create pgvector extension
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            
            # Create tables
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {str(e)}")
        raise

async def get_db() -> AsyncSession:
    """Get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# Utility functions for database operations
async def get_user_by_email(email: str) -> Optional[dict]:
    """Get user by email"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        if user:
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "google_id": user.google_id,
                "hubspot_id": user.hubspot_id,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
                "google_access_token": user.google_access_token,
                "google_refresh_token": user.google_refresh_token,
                "google_token_expires_at": user.google_token_expires_at,
                "hubspot_access_token": user.hubspot_access_token,
                "hubspot_refresh_token": user.hubspot_refresh_token,
                "hubspot_token_expires_at": user.hubspot_token_expires_at,
            }
        return None

async def get_user_by_google_id(google_id: str) -> Optional[dict]:
    """Get user by Google ID"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.google_id == google_id)
        )
        user = result.scalar_one_or_none()
        if user:
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "google_id": user.google_id,
                "hubspot_id": user.hubspot_id,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
                "google_access_token": user.google_access_token,
                "google_refresh_token": user.google_refresh_token,
                "google_token_expires_at": user.google_token_expires_at,
                "hubspot_access_token": user.hubspot_access_token,
                "hubspot_refresh_token": user.hubspot_refresh_token,
                "hubspot_token_expires_at": user.hubspot_token_expires_at,
            }
        return None

async def create_user(user_data: dict) -> dict:
    """Create a new user"""
    async with AsyncSessionLocal() as session:
        user = User(
            id=str(uuid.uuid4()),
            email=user_data["email"],
            name=user_data.get("name"),
            google_id=user_data.get("google_id"),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "google_id": user.google_id,
            "hubspot_id": user.hubspot_id,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        } 