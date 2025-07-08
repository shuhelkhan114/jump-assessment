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

# Enhanced connection pool settings for better concurrent access handling
engine = create_async_engine(
    async_database_url, 
    echo=settings.debug,
    # Connection pool settings to handle concurrent access
    pool_size=20,          # Number of connections to maintain in the pool
    max_overflow=30,       # Additional connections beyond pool_size
    pool_timeout=30,       # Timeout for getting connection from pool
    pool_recycle=3600,     # Recycle connections after 1 hour
    pool_pre_ping=True,    # Validate connections before use
    # Asyncpg specific settings
    connect_args={
        "server_settings": {
            "jit": "off",  # Disable JIT for stability
        },
        "command_timeout": 30,  # Command timeout in seconds
    }
)

AsyncSessionLocal = async_sessionmaker(
    engine, 
    class_=AsyncSession, 
    expire_on_commit=False,
    # Add session-level timeout protection
    autoflush=True,
    autocommit=False
)

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
    chat_sessions = relationship("ChatSession", back_populates="user")
    conversations = relationship("Conversation", back_populates="user")
    ongoing_instructions = relationship("OngoingInstruction", back_populates="user")
    hubspot_contacts = relationship("HubspotContact", back_populates="user")
    hubspot_deals = relationship("HubspotDeal", back_populates="user")
    hubspot_companies = relationship("HubspotCompany", back_populates="user")
    calendar_events = relationship("CalendarEvent", back_populates="user")
    workflows = relationship("Workflow", back_populates="user")
    events = relationship("Event", back_populates="user")

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
    user = relationship("User", back_populates="hubspot_contacts")
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
    user = relationship("User", back_populates="hubspot_deals")
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
    user = relationship("User", back_populates="hubspot_companies")
    deals = relationship("HubspotDeal", back_populates="company")

class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    google_event_id = Column(String, nullable=False)
    calendar_id = Column(String, nullable=True, default="primary")
    title = Column(String, nullable=True)  # summary in Google Calendar
    description = Column(Text, nullable=True)
    location = Column(String, nullable=True)
    start_datetime = Column(DateTime, nullable=True)
    end_datetime = Column(DateTime, nullable=True)
    start_date = Column(String, nullable=True)  # For all-day events
    end_date = Column(String, nullable=True)    # For all-day events
    is_all_day = Column(Boolean, default=False)
    status = Column(String, nullable=True)  # confirmed, tentative, cancelled
    organizer_email = Column(String, nullable=True)
    organizer_name = Column(String, nullable=True)
    attendees = Column(Text, nullable=True)  # JSON string of attendees
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Vector embedding for RAG
    embedding = Column(Vector(1536), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="calendar_events")

class ChatSession(Base):
    __tablename__ = "chat_sessions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=True)  # Auto-generated or user-set title
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="chat_sessions")
    conversations = relationship("Conversation", back_populates="chat_session", order_by="Conversation.created_at")

class Conversation(Base):
    __tablename__ = "conversations"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    chat_session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    message = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    context_used = Column(Text, nullable=True)  # RAG context
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="conversations")
    chat_session = relationship("ChatSession", back_populates="conversations")

class OngoingInstruction(Base):
    __tablename__ = "ongoing_instructions"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    instruction = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    
    # Enhanced fields for trigger-based instructions
    trigger_conditions = Column(Text, nullable=True)  # JSON conditions for when to trigger
    priority = Column(Integer, default=0)  # Higher numbers = higher priority
    event_types = Column(Text, nullable=True)  # JSON array of event types this applies to
    
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

# Workflow Engine Models
class WorkflowTemplate(Base):
    __tablename__ = "workflow_templates"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False, unique=True)
    description = Column(Text, nullable=True)
    template_data = Column(Text, nullable=False)  # JSON workflow definition
    version = Column(String, default="1.0")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    workflows = relationship("Workflow", back_populates="template")

class Workflow(Base):
    __tablename__ = "workflows"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    template_id = Column(String, ForeignKey("workflow_templates.id"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    
    # Workflow execution state
    status = Column(String, default="pending")  # pending, running, waiting, completed, failed, cancelled
    current_step = Column(Integer, default=0)
    context = Column(Text, nullable=True)  # JSON context data for the workflow
    input_data = Column(Text, nullable=True)  # JSON initial input data
    output_data = Column(Text, nullable=True)  # JSON final output data
    
    # Timing and scheduling
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    next_execution_at = Column(DateTime, nullable=True)  # For scheduled/waiting workflows
    timeout_at = Column(DateTime, nullable=True)  # When workflow should timeout
    
    # Metadata
    triggered_by_event_id = Column(String, ForeignKey("events.id"), nullable=True)
    parent_workflow_id = Column(String, ForeignKey("workflows.id"), nullable=True)
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="workflows")
    template = relationship("WorkflowTemplate", back_populates="workflows")
    steps = relationship("WorkflowStep", back_populates="workflow", order_by="WorkflowStep.step_number")
    triggered_by_event = relationship("Event", foreign_keys=[triggered_by_event_id])
    parent_workflow = relationship("Workflow", remote_side=[id])
    child_workflows = relationship("Workflow", remote_side=[parent_workflow_id])

class WorkflowStep(Base):
    __tablename__ = "workflow_steps"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id = Column(String, ForeignKey("workflows.id"), nullable=False)
    step_number = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    step_type = Column(String, nullable=False)  # tool_call, condition, wait, ai_decision, etc.
    
    # Step execution state
    status = Column(String, default="pending")  # pending, running, completed, failed, skipped
    input_data = Column(Text, nullable=True)  # JSON input for this step
    output_data = Column(Text, nullable=True)  # JSON output from this step
    error_message = Column(Text, nullable=True)
    
    # Step configuration
    config = Column(Text, nullable=True)  # JSON configuration for the step
    timeout_seconds = Column(Integer, default=300)  # 5 minute default timeout
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=2)
    
    # Conditional execution
    condition = Column(Text, nullable=True)  # JSON condition for when to execute this step
    depends_on_steps = Column(Text, nullable=True)  # JSON array of step numbers this depends on
    
    # Timing
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    workflow = relationship("Workflow", back_populates="steps")

class Event(Base):
    __tablename__ = "events"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    
    # Event identification
    source = Column(String, nullable=False)  # gmail, calendar, hubspot, manual
    event_type = Column(String, nullable=False)  # email_received, contact_created, etc.
    external_id = Column(String, nullable=True)  # ID from the external system
    
    # Event data
    data = Column(Text, nullable=False)  # JSON event payload
    event_metadata = Column(Text, nullable=True)  # JSON additional metadata
    
    # Processing state
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime, nullable=True)
    processing_error = Column(Text, nullable=True)
    
    # Workflow tracking
    triggered_workflows = Column(Text, nullable=True)  # JSON array of workflow IDs triggered by this event
    
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="events")
    workflows = relationship("Workflow", foreign_keys="Workflow.triggered_by_event_id")

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

async def get_user_by_id(user_id: str) -> Optional[dict]:
    """Get user by ID"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
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