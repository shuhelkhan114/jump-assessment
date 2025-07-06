"""
Celery tasks for HubSpot data synchronization and processing
"""
from celery import Celery
from typing import Dict, Any, List
import asyncio
import json
import structlog
from datetime import datetime
from sqlalchemy import text, create_engine, select
from sqlalchemy.orm import sessionmaker

from database import User, HubspotContact, HubspotDeal, HubspotCompany
from services.hubspot_service import hubspot_service
from services.openai_service import openai_service
from celery_app import celery_app
from config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Create synchronous database engine for Celery tasks
sync_engine = create_engine(settings.database_url, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine)

@celery_app.task(bind=True, max_retries=3)
def sync_hubspot_contacts(self, user_id: str):
    """Sync HubSpot contacts for a user"""
    try:
        logger.info(f"Starting HubSpot contacts sync for user {user_id}")
        
        # Run sync function
        result = _sync_hubspot_contacts_sync(user_id)
        
        logger.info(f"HubSpot contacts sync completed for user {user_id}: {result}")
        return result
        
    except Exception as e:
        logger.error(f"HubSpot contacts sync failed for user {user_id}: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_hubspot_contacts_sync(user_id: str) -> Dict[str, Any]:
    """Sync implementation of HubSpot contacts sync"""
    with SyncSessionLocal() as session:
        # Get user with OAuth tokens
        result = session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise Exception(f"User {user_id} not found")
        
        if not user.hubspot_access_token:
            raise Exception(f"User {user_id} has no HubSpot access token")
        
        # Initialize HubSpot service
        if not hubspot_service.initialize_service(user.hubspot_access_token):
            raise Exception("Failed to initialize HubSpot service")
        
        # Get existing HubSpot contact IDs to avoid duplicates
        existing_result = session.execute(
            select(HubspotContact.hubspot_id).where(HubspotContact.user_id == user_id)
        )
        existing_hubspot_ids = {row[0] for row in existing_result.fetchall()}
        
        # Fetch contacts from HubSpot with pagination
        all_contacts = []
        after = None
        
        while True:
            contacts_data = asyncio.run(hubspot_service.get_contacts(limit=100, after=after))
            contacts = contacts_data.get('results', [])
            
            if not contacts:
                break
                
            all_contacts.extend(contacts)
            
            # Check for pagination
            paging = contacts_data.get('paging', {})
            if 'next' in paging:
                after = paging['next']['after']
            else:
                break
        
        new_contacts = []
        processed_count = 0
        
        for contact_data in all_contacts:
            hubspot_id = contact_data['id']
            
            # Skip if already processed
            if hubspot_id in existing_hubspot_ids:
                continue
            
            try:
                # Extract contact properties
                properties = contact_data.get('properties', {})
                
                # Parse date fields
                notes_last_contacted = _parse_hubspot_date(properties.get('notes_last_contacted'))
                notes_last_activity_date = _parse_hubspot_date(properties.get('notes_last_activity_date'))
                
                # Create contact record
                contact = HubspotContact(
                    user_id=user_id,
                    hubspot_id=hubspot_id,
                    firstname=properties.get('firstname'),
                    lastname=properties.get('lastname'),
                    email=properties.get('email'),
                    phone=properties.get('phone'),
                    company=properties.get('company'),
                    jobtitle=properties.get('jobtitle'),
                    industry=properties.get('industry'),
                    lifecyclestage=properties.get('lifecyclestage'),
                    lead_status=properties.get('lead_status'),
                    notes_last_contacted=notes_last_contacted,
                    notes_last_activity_date=notes_last_activity_date,
                    num_notes=_parse_int(properties.get('num_notes')),
                    properties=json.dumps(properties)
                )
                
                session.add(contact)
                new_contacts.append(contact)
                processed_count += 1
                
                # Commit in batches
                if processed_count % 20 == 0:
                    session.commit()
                    logger.info(f"Processed {processed_count} contacts for user {user_id}")
                
            except Exception as e:
                logger.error(f"Failed to process contact {hubspot_id}: {str(e)}")
                continue
        
        # Final commit
        session.commit()
        
        # Schedule embedding generation for new contacts
        if new_contacts:
            generate_hubspot_embeddings.delay(user_id, 'contacts', [contact.id for contact in new_contacts])
        
        # Close HubSpot service
        asyncio.run(hubspot_service.close())
        
        return {
            "user_id": user_id,
            "total_contacts": len(all_contacts),
            "new_contacts": len(new_contacts),
            "processed_count": processed_count,
            "synced_at": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True, max_retries=3)
def sync_hubspot_deals(self, user_id: str):
    """Sync HubSpot deals for a user"""
    try:
        logger.info(f"Starting HubSpot deals sync for user {user_id}")
        
        # Run sync function
        result = _sync_hubspot_deals_sync(user_id)
        
        logger.info(f"HubSpot deals sync completed for user {user_id}: {result}")
        return result
        
    except Exception as e:
        logger.error(f"HubSpot deals sync failed for user {user_id}: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_hubspot_deals_sync(user_id: str) -> Dict[str, Any]:
    """Sync implementation of HubSpot deals sync"""
    with SyncSessionLocal() as session:
        # Get user with OAuth tokens
        result = session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise Exception(f"User {user_id} not found")
        
        if not user.hubspot_access_token:
            raise Exception(f"User {user_id} has no HubSpot access token")
        
        # Initialize HubSpot service
        if not hubspot_service.initialize_service(user.hubspot_access_token):
            raise Exception("Failed to initialize HubSpot service")
        
        # Get existing HubSpot deal IDs to avoid duplicates
        existing_result = session.execute(
            select(HubspotDeal.hubspot_id).where(HubspotDeal.user_id == user_id)
        )
        existing_hubspot_ids = {row[0] for row in existing_result.fetchall()}
        
        # Fetch deals from HubSpot with pagination
        all_deals = []
        after = None
        
        while True:
            deals_data = asyncio.run(hubspot_service.get_deals(limit=100, after=after))
            deals = deals_data.get('results', [])
            
            if not deals:
                break
                
            all_deals.extend(deals)
            
            # Check for pagination
            paging = deals_data.get('paging', {})
            if 'next' in paging:
                after = paging['next']['after']
            else:
                break
        
        new_deals = []
        processed_count = 0
        
        for deal_data in all_deals:
            hubspot_id = deal_data['id']
            
            # Skip if already processed
            if hubspot_id in existing_hubspot_ids:
                continue
            
            try:
                # Extract deal properties
                properties = deal_data.get('properties', {})
                
                # Parse date fields
                closedate = _parse_hubspot_date(properties.get('closedate'))
                notes_last_contacted = _parse_hubspot_date(properties.get('notes_last_contacted'))
                notes_last_activity_date = _parse_hubspot_date(properties.get('notes_last_activity_date'))
                
                # Create deal record
                deal = HubspotDeal(
                    user_id=user_id,
                    hubspot_id=hubspot_id,
                    dealname=properties.get('dealname'),
                    amount=_parse_float(properties.get('amount')),
                    dealstage=properties.get('dealstage'),
                    pipeline=properties.get('pipeline'),
                    closedate=closedate,
                    dealtype=properties.get('dealtype'),
                    description=properties.get('description'),
                    notes_last_contacted=notes_last_contacted,
                    notes_last_activity_date=notes_last_activity_date,
                    num_notes=_parse_int(properties.get('num_notes')),
                    hubspot_owner_id=properties.get('hubspot_owner_id'),
                    properties=json.dumps(properties)
                )
                
                session.add(deal)
                new_deals.append(deal)
                processed_count += 1
                
                # Commit in batches
                if processed_count % 20 == 0:
                    session.commit()
                    logger.info(f"Processed {processed_count} deals for user {user_id}")
                
            except Exception as e:
                logger.error(f"Failed to process deal {hubspot_id}: {str(e)}")
                continue
        
        # Final commit
        session.commit()
        
        # Schedule embedding generation for new deals
        if new_deals:
            generate_hubspot_embeddings.delay(user_id, 'deals', [deal.id for deal in new_deals])
        
        # Close HubSpot service
        asyncio.run(hubspot_service.close())
        
        return {
            "user_id": user_id,
            "total_deals": len(all_deals),
            "new_deals": len(new_deals),
            "processed_count": processed_count,
            "synced_at": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True, max_retries=3)
def sync_hubspot_companies(self, user_id: str):
    """Sync HubSpot companies for a user"""
    try:
        logger.info(f"Starting HubSpot companies sync for user {user_id}")
        
        # Run sync function
        result = _sync_hubspot_companies_sync(user_id)
        
        logger.info(f"HubSpot companies sync completed for user {user_id}: {result}")
        return result
        
    except Exception as e:
        logger.error(f"HubSpot companies sync failed for user {user_id}: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_hubspot_companies_sync(user_id: str) -> Dict[str, Any]:
    """Sync implementation of HubSpot companies sync"""
    with SyncSessionLocal() as session:
        # Get user with OAuth tokens
        result = session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user:
            raise Exception(f"User {user_id} not found")
        
        if not user.hubspot_access_token:
            raise Exception(f"User {user_id} has no HubSpot access token")
        
        # Initialize HubSpot service
        if not hubspot_service.initialize_service(user.hubspot_access_token):
            raise Exception("Failed to initialize HubSpot service")
        
        # Get existing HubSpot company IDs to avoid duplicates
        existing_result = session.execute(
            select(HubspotCompany.hubspot_id).where(HubspotCompany.user_id == user_id)
        )
        existing_hubspot_ids = {row[0] for row in existing_result.fetchall()}
        
        # Fetch companies from HubSpot with pagination
        all_companies = []
        after = None
        
        while True:
            companies_data = asyncio.run(hubspot_service.get_companies(limit=100, after=after))
            companies = companies_data.get('results', [])
            
            if not companies:
                break
                
            all_companies.extend(companies)
            
            # Check for pagination
            paging = companies_data.get('paging', {})
            if 'next' in paging:
                after = paging['next']['after']
            else:
                break
        
        new_companies = []
        processed_count = 0
        
        for company_data in all_companies:
            hubspot_id = company_data['id']
            
            # Skip if already processed
            if hubspot_id in existing_hubspot_ids:
                continue
            
            try:
                # Extract company properties
                properties = company_data.get('properties', {})
                
                # Parse date fields
                notes_last_contacted = _parse_hubspot_date(properties.get('notes_last_contacted'))
                notes_last_activity_date = _parse_hubspot_date(properties.get('notes_last_activity_date'))
                
                # Create company record
                company = HubspotCompany(
                    user_id=user_id,
                    hubspot_id=hubspot_id,
                    name=properties.get('name'),
                    domain=properties.get('domain'),
                    industry=properties.get('industry'),
                    type=properties.get('type'),
                    description=properties.get('description'),
                    phone=properties.get('phone'),
                    address=properties.get('address'),
                    city=properties.get('city'),
                    state=properties.get('state'),
                    country=properties.get('country'),
                    num_employees=_parse_int(properties.get('num_employees')),
                    annualrevenue=_parse_float(properties.get('annualrevenue')),
                    notes_last_contacted=notes_last_contacted,
                    notes_last_activity_date=notes_last_activity_date,
                    num_notes=_parse_int(properties.get('num_notes')),
                    properties=json.dumps(properties)
                )
                
                session.add(company)
                new_companies.append(company)
                processed_count += 1
                
                # Commit in batches
                if processed_count % 20 == 0:
                    session.commit()
                    logger.info(f"Processed {processed_count} companies for user {user_id}")
                
            except Exception as e:
                logger.error(f"Failed to process company {hubspot_id}: {str(e)}")
                continue
        
        # Final commit
        session.commit()
        
        # Schedule embedding generation for new companies
        if new_companies:
            generate_hubspot_embeddings.delay(user_id, 'companies', [company.id for company in new_companies])
        
        # Close HubSpot service
        asyncio.run(hubspot_service.close())
        
        return {
            "user_id": user_id,
            "total_companies": len(all_companies),
            "new_companies": len(new_companies),
            "processed_count": processed_count,
            "synced_at": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True, max_retries=3)
def generate_hubspot_embeddings(self, user_id: str, object_type: str, object_ids: List[str]):
    """Generate embeddings for HubSpot objects"""
    try:
        logger.info(f"Starting embedding generation for {len(object_ids)} {object_type}")
        
        # Run sync function
        result = _generate_hubspot_embeddings_sync(user_id, object_type, object_ids)
        
        logger.info(f"HubSpot embedding generation completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"HubSpot embedding generation failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _generate_hubspot_embeddings_sync(user_id: str, object_type: str, object_ids: List[str]) -> Dict[str, Any]:
    """Sync implementation of HubSpot embedding generation"""
    with SyncSessionLocal() as session:
        # Get objects without embeddings based on type
        if object_type == 'contacts':
            model_class = HubspotContact
            text_creator = _create_contact_text_for_embedding
        elif object_type == 'deals':
            model_class = HubspotDeal
            text_creator = _create_deal_text_for_embedding
        elif object_type == 'companies':
            model_class = HubspotCompany
            text_creator = _create_company_text_for_embedding
        else:
            raise ValueError(f"Unknown object type: {object_type}")
        
        result = session.execute(
            select(model_class).where(
                model_class.user_id == user_id,
                model_class.id.in_(object_ids),
                model_class.embedding.is_(None)
            )
        )
        objects = result.scalars().all()
        
        processed_count = 0
        
        for obj in objects:
            try:
                # Create text for embedding
                obj_text = text_creator(obj)
                
                # Generate embedding
                embedding = asyncio.run(openai_service.generate_embedding(obj_text))
                
                if embedding:
                    # Update object with embedding
                    obj.embedding = embedding
                    processed_count += 1
                    
                    # Commit in batches
                    if processed_count % 5 == 0:
                        session.commit()
                        logger.info(f"Generated embeddings for {processed_count} {object_type}")
                
            except Exception as e:
                logger.error(f"Failed to generate embedding for {object_type} {obj.id}: {str(e)}")
                continue
        
        # Final commit
        session.commit()
        
        return {
            "user_id": user_id,
            "object_type": object_type,
            "total_objects": len(objects),
            "processed_count": processed_count,
            "generated_at": datetime.utcnow().isoformat()
        }

@celery_app.task(bind=True, max_retries=3)
def sync_all_hubspot_data(self, user_id: str):
    """Sync all HubSpot data for a user"""
    try:
        logger.info(f"Starting full HubSpot sync for user {user_id}")
        
        # Schedule individual sync tasks
        contacts_task = sync_hubspot_contacts.delay(user_id)
        deals_task = sync_hubspot_deals.delay(user_id)
        companies_task = sync_hubspot_companies.delay(user_id)
        
        return {
            "user_id": user_id,
            "contacts_task_id": contacts_task.id,
            "deals_task_id": deals_task.id,
            "companies_task_id": companies_task.id,
            "synced_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"HubSpot full sync failed for user {user_id}: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

# Utility functions
def _parse_hubspot_date(date_str: str) -> datetime:
    """Parse HubSpot date string to datetime"""
    if not date_str:
        return None
    
    try:
        # HubSpot uses Unix timestamp in milliseconds
        timestamp = int(date_str) / 1000
        return datetime.fromtimestamp(timestamp)
    except (ValueError, TypeError):
        logger.warning(f"Could not parse HubSpot date: {date_str}")
        return None

def _parse_int(value: Any) -> int:
    """Parse integer value safely"""
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

def _parse_float(value: Any) -> float:
    """Parse float value safely"""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def _create_contact_text_for_embedding(contact: HubspotContact) -> str:
    """Create text representation of contact for embedding"""
    parts = []
    
    # Add name
    if contact.firstname or contact.lastname:
        name = f"{contact.firstname or ''} {contact.lastname or ''}".strip()
        parts.append(f"Name: {name}")
    
    # Add email
    if contact.email:
        parts.append(f"Email: {contact.email}")
    
    # Add company and job title
    if contact.company:
        parts.append(f"Company: {contact.company}")
    
    if contact.jobtitle:
        parts.append(f"Job Title: {contact.jobtitle}")
    
    # Add industry and lifecycle stage
    if contact.industry:
        parts.append(f"Industry: {contact.industry}")
    
    if contact.lifecyclestage:
        parts.append(f"Lifecycle Stage: {contact.lifecyclestage}")
    
    # Add phone
    if contact.phone:
        parts.append(f"Phone: {contact.phone}")
    
    return "\n".join(parts)

def _create_deal_text_for_embedding(deal: HubspotDeal) -> str:
    """Create text representation of deal for embedding"""
    parts = []
    
    # Add deal name
    if deal.dealname:
        parts.append(f"Deal: {deal.dealname}")
    
    # Add amount
    if deal.amount:
        parts.append(f"Amount: ${deal.amount}")
    
    # Add stage and pipeline
    if deal.dealstage:
        parts.append(f"Stage: {deal.dealstage}")
    
    if deal.pipeline:
        parts.append(f"Pipeline: {deal.pipeline}")
    
    # Add description
    if deal.description:
        parts.append(f"Description: {deal.description}")
    
    # Add close date
    if deal.closedate:
        parts.append(f"Close Date: {deal.closedate.strftime('%Y-%m-%d')}")
    
    return "\n".join(parts)

def _create_company_text_for_embedding(company: HubspotCompany) -> str:
    """Create text representation of company for embedding"""
    parts = []
    
    # Add company name
    if company.name:
        parts.append(f"Company: {company.name}")
    
    # Add domain
    if company.domain:
        parts.append(f"Domain: {company.domain}")
    
    # Add industry
    if company.industry:
        parts.append(f"Industry: {company.industry}")
    
    # Add description
    if company.description:
        parts.append(f"Description: {company.description}")
    
    # Add size and revenue
    if company.num_employees:
        parts.append(f"Employees: {company.num_employees}")
    
    if company.annualrevenue:
        parts.append(f"Annual Revenue: ${company.annualrevenue}")
    
    # Add location
    location_parts = []
    if company.city:
        location_parts.append(company.city)
    if company.state:
        location_parts.append(company.state)
    if company.country:
        location_parts.append(company.country)
    
    if location_parts:
        parts.append(f"Location: {', '.join(location_parts)}")
    
    return "\n".join(parts) 