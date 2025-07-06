from celery import Task
from celery_app import celery_app
import structlog

logger = structlog.get_logger()

@celery_app.task(bind=True)
def generate_embeddings(self, text_data: list, user_id: str):
    """Generate embeddings for text data using OpenAI"""
    try:
        logger.info(f"Generating embeddings for {len(text_data)} texts for user {user_id}")
        
        # TODO: Implement OpenAI embeddings generation
        # This will involve:
        # 1. Calling OpenAI embeddings API
        # 2. Processing the response
        # 3. Storing embeddings in database
        
        logger.info(f"Embeddings generated successfully for user {user_id}")
        return {"status": "success", "user_id": user_id, "count": len(text_data)}
        
    except Exception as e:
        logger.error(f"Embeddings generation failed: {str(e)}")
        raise self.retry(exc=e, countdown=60, max_retries=3)

@celery_app.task(bind=True)
def process_ai_chat(self, user_id: str, message: str, context: dict = None):
    """Process AI chat message with RAG"""
    try:
        logger.info(f"Processing AI chat for user {user_id}")
        
        # TODO: Implement AI chat processing
        # This will involve:
        # 1. RAG search for relevant context
        # 2. Calling OpenAI Chat API
        # 3. Processing tools/function calls
        # 4. Storing conversation in database
        
        logger.info(f"AI chat processed successfully for user {user_id}")
        return {"status": "success", "user_id": user_id, "message": "Chat processed"}
        
    except Exception as e:
        logger.error(f"AI chat processing failed: {str(e)}")
        raise self.retry(exc=e, countdown=30, max_retries=3)

@celery_app.task(bind=True)
def execute_ai_action(self, user_id: str, action_type: str, action_data: dict):
    """Execute AI-requested actions (send email, create meeting, etc.)"""
    try:
        logger.info(f"Executing AI action {action_type} for user {user_id} with data: {action_data}")
        
        if action_type == "send_email":
            return _execute_send_email(user_id, action_data)
        elif action_type == "create_calendar_event":
            return _execute_create_calendar_event(user_id, action_data)
        elif action_type == "create_hubspot_contact":
            return _execute_create_hubspot_contact(user_id, action_data)
        else:
            raise ValueError(f"Unknown action type: {action_type}")
        
    except Exception as e:
        logger.error(f"AI action execution failed: {str(e)}")
        raise self.retry(exc=e, countdown=30, max_retries=3)

def _execute_send_email(user_id: str, action_data: dict) -> dict:
    """Execute send email action"""
    from tasks.gmail_tasks import _send_email_sync
    
    try:
        # Extract email parameters
        to = action_data.get("to")
        subject = action_data.get("subject")
        body = action_data.get("body")
        cc = action_data.get("cc")
        
        # Validate required parameters
        if not all([to, subject, body]):
            raise ValueError("Missing required email parameters: to, subject, body")
        
        # Send email using existing Gmail task function
        result = _send_email_sync(user_id, to, subject, body, cc)
        
        logger.info(f"Email sent successfully to {to}")
        return {
            "action": "send_email",
            "status": "success",
            "message": f"Email sent successfully to {to}",
            "details": result
        }
        
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        raise e

def _execute_create_calendar_event(user_id: str, action_data: dict) -> dict:
    """Execute create calendar event action"""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from database import User
    from services.gmail_service import gmail_service
    from config import get_settings
    import asyncio
    
    logger.info(f"Creating calendar event for user {user_id}: {action_data}")
    
    try:
        # Extract calendar parameters
        title = action_data.get("title")
        start_datetime = action_data.get("start_datetime")
        end_datetime = action_data.get("end_datetime")
        description = action_data.get("description", "")
        attendees = action_data.get("attendees", [])
        location = action_data.get("location", "")
        
        if not all([title, start_datetime, end_datetime]):
            raise ValueError("Missing required calendar parameters: title, start_datetime, end_datetime")
        
        # Get user with OAuth tokens (synchronous database access for Celery)
        settings = get_settings()
        sync_engine = create_engine(settings.database_url, echo=False)
        SyncSessionLocal = sessionmaker(bind=sync_engine)
        
        with SyncSessionLocal() as session:
            user_result = session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                raise Exception(f"User {user_id} not found")
            
            if not user.google_access_token:
                raise Exception(f"User {user_id} has no Google access token")
            
            # Initialize Gmail service with Calendar support
            if not gmail_service.initialize_service(
                user.google_access_token,
                user.google_refresh_token or ""
            ):
                raise Exception("Failed to initialize Gmail/Calendar service")
            
            # Create calendar event
            calendar_result = asyncio.run(gmail_service.create_calendar_event(
                title=title,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                description=description,
                attendees=attendees,
                location=location
            ))
            
            logger.info(f"Calendar event '{title}' created successfully with ID: {calendar_result.get('id')}")
            
            return {
                "action": "create_calendar_event",
                "status": "success",
                "message": f"Calendar event '{title}' created successfully",
                "details": {
                    "id": calendar_result.get("id"),
                    "title": title,
                    "start": start_datetime,
                    "end": end_datetime,
                    "attendees": attendees,
                    "location": location,
                    "link": calendar_result.get("htmlLink", "")
                }
            }
        
    except Exception as e:
        logger.error(f"Failed to create calendar event: {str(e)}")
        raise e

def _execute_create_hubspot_contact(user_id: str, action_data: dict) -> dict:
    """Execute create HubSpot contact action"""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from database import User
    from services.hubspot_service import HubSpotService
    from config import get_settings
    import asyncio
    
    logger.info(f"Creating HubSpot contact for user {user_id}: {action_data}")
    
    try:
        # Extract contact parameters
        email = action_data.get("email")
        firstname = action_data.get("firstname")
        lastname = action_data.get("lastname")
        company = action_data.get("company", "")
        jobtitle = action_data.get("jobtitle", "")
        phone = action_data.get("phone", "")
        
        if not all([email, firstname, lastname]):
            raise ValueError("Missing required contact parameters: email, firstname, lastname")
        
        # Get user with HubSpot OAuth token (synchronous database access for Celery)
        settings = get_settings()
        sync_engine = create_engine(settings.database_url, echo=False)
        SyncSessionLocal = sessionmaker(bind=sync_engine)
        
        with SyncSessionLocal() as session:
            user_result = session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                raise Exception(f"User {user_id} not found")
            
            if not user.hubspot_access_token:
                raise Exception(f"User {user_id} has no HubSpot access token")
            
            # Initialize HubSpot service
            hubspot_service = HubSpotService()
            if not hubspot_service.initialize_service(user.hubspot_access_token):
                raise Exception("Failed to initialize HubSpot service")
            
            # Prepare contact data for HubSpot
            contact_data = {
                "email": email,
                "firstname": firstname,
                "lastname": lastname,
            }
            
            # Add optional fields if provided
            if company:
                contact_data["company"] = company
            if jobtitle:
                contact_data["jobtitle"] = jobtitle
            if phone:
                contact_data["phone"] = phone
            
            # Create contact in HubSpot
            create_result = asyncio.run(hubspot_service.create_contact(contact_data))
            
            # Close HubSpot client
            hubspot_service.close_sync()
            
            contact_name = f"{firstname} {lastname}"
            
            # Handle different response types
            if create_result.get("_status") == "existing":
                contact_id = create_result.get("id")
                logger.info(f"Found existing HubSpot contact '{contact_name}' with ID: {contact_id}")
                return {
                    "action": "create_hubspot_contact",
                    "status": "success",
                    "message": f"Contact '{contact_name}' already exists in HubSpot",
                    "details": {
                        "id": contact_id,
                        "name": contact_name,
                        "email": email,
                        "company": company,
                        "jobtitle": jobtitle,
                        "phone": phone,
                        "properties": create_result.get("properties", {}),
                        "status": "existing"
                    }
                }
            elif create_result.get("_status") == "conflict":
                logger.info(f"Contact conflict resolved for '{contact_name}': {create_result.get('_message')}")
                return {
                    "action": "create_hubspot_contact",
                    "status": "success",
                    "message": f"Contact '{contact_name}' already exists in HubSpot",
                    "details": {
                        "name": contact_name,
                        "email": email,
                        "company": company,
                        "jobtitle": jobtitle,
                        "phone": phone,
                        "status": "conflict"
                    }
                }
            else:
                # New contact created successfully
                contact_id = create_result.get("id")
                logger.info(f"HubSpot contact '{contact_name}' created successfully with ID: {contact_id}")
                return {
                    "action": "create_hubspot_contact",
                    "status": "success",
                    "message": f"Contact '{contact_name}' created successfully in HubSpot",
                    "details": {
                        "id": contact_id,
                        "name": contact_name,
                        "email": email,
                        "company": company,
                        "jobtitle": jobtitle,
                        "phone": phone,
                        "properties": create_result.get("properties", {}),
                        "status": "created"
                    }
                }
        
    except Exception as e:
        logger.error(f"Failed to create HubSpot contact: {str(e)}")
        raise e

@celery_app.task(bind=True)
def update_vector_search_index(self, user_id: str, content_type: str):
    """Update vector search index for a user"""
    try:
        logger.info(f"Updating vector search index for user {user_id}, type: {content_type}")
        
        # TODO: Implement vector index updates
        # This will refresh embeddings and optimize search indices
        
        logger.info(f"Vector search index updated successfully")
        return {"status": "success", "user_id": user_id, "content_type": content_type}
        
    except Exception as e:
        logger.error(f"Vector search index update failed: {str(e)}")
        raise self.retry(exc=e, countdown=60, max_retries=3) 