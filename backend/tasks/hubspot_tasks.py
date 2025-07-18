"""
Celery tasks for HubSpot data synchronization and processing
"""
from celery import Celery
from typing import Dict, Any, List
import asyncio
import json
import structlog
from datetime import datetime, timedelta
from sqlalchemy import text, create_engine, select, update
from sqlalchemy.orm import sessionmaker
import requests

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

def _refresh_hubspot_token_sync(user_id: str, session) -> bool:
    """
    Synchronously refresh HubSpot token for a user
    Returns True if successful, False otherwise
    """
    try:
        # Get user
        result = session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        
        if not user or not user.hubspot_refresh_token:
            logger.error(f"User {user_id} not found or has no HubSpot refresh token")
            return False
        
        logger.info(f"Refreshing HubSpot token for user {user_id}")
        
        # Refresh HubSpot token using OAuth2 refresh flow
        response = requests.post(
            "https://api.hubapi.com/oauth/v1/token",
            data={
                "grant_type": "refresh_token",
                "client_id": settings.hubspot_client_id,
                "client_secret": settings.hubspot_client_secret,
                "refresh_token": user.hubspot_refresh_token
            },
            timeout=30
        )
        
        if response.status_code == 200:
            token_data = response.json()
            
            # Update user tokens
            session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    hubspot_access_token=token_data["access_token"],
                    hubspot_refresh_token=token_data.get("refresh_token", user.hubspot_refresh_token),
                    hubspot_token_expires_at=datetime.utcnow() + timedelta(seconds=token_data.get("expires_in", 21600)),
                    updated_at=datetime.utcnow()
                )
            )
            session.commit()
            
            logger.info(f"Successfully refreshed HubSpot token for user {user_id}")
            return True
        else:
            logger.error(f"Failed to refresh HubSpot token for user {user_id}: HTTP {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error refreshing HubSpot token for user {user_id}: {str(e)}")
        return False

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
        error_str = str(e).lower()
        logger.error(f"HubSpot contacts sync failed for user {user_id}: {str(e)}")
        
        # Check if this is a 401 error and we should try to refresh token
        if "401" in error_str:
            logger.warning(f"🔄 Detected 401 error in HubSpot contacts sync, user {user_id} needs token refresh")
            
            # Try to refresh token before retrying
            try:
                with SyncSessionLocal() as session:
                    if _refresh_hubspot_token_sync(user_id, session):
                        logger.info(f"✅ Token refreshed successfully for user {user_id}, task will retry")
                    else:
                        logger.error(f"❌ Token refresh failed for user {user_id}")
            except Exception as refresh_error:
                logger.error(f"❌ Token refresh error for user {user_id}: {str(refresh_error)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_hubspot_contacts_sync(user_id: str) -> Dict[str, Any]:
    """Sync implementation of HubSpot contacts sync"""
    max_token_refresh_attempts = 2
    
    for attempt in range(max_token_refresh_attempts):
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
            
            try:
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
                        try:
                            # Try to create contact with thank you email fields
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
                                properties=json.dumps(properties),
                                # Thank you email fields with defaults
                                thank_you_email_sent=False,
                                thank_you_email_sent_at=None,
                                # Set context as customer since this was synced from HubSpot
                                contact_creation_context="customer"
                            )
                        except TypeError as te:
                            # Check if this is due to missing thank you email fields
                            if "thank_you_email_sent" in str(te):
                                logger.warning(f"⚠️ Thank you email fields not yet migrated, creating contact without them for {hubspot_id}")
                                # Create contact without thank you email fields
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
                                    properties=json.dumps(properties),
                                    # Set context as customer since this was synced from HubSpot
                                    contact_creation_context="customer"
                                )
                            else:
                                raise te
                        
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
                hubspot_service.close_sync()
                
                return {
                    "user_id": user_id,
                    "total_contacts": len(all_contacts),
                    "new_contacts": len(new_contacts),
                    "processed_count": processed_count,
                    "synced_at": datetime.utcnow().isoformat()
                }
                
            except Exception as e:
                error_str = str(e).lower()
                
                # Check if this is a 401 error and we haven't exhausted retry attempts
                if "401" in error_str and attempt < max_token_refresh_attempts - 1:
                    logger.warning(f"🔄 HubSpot 401 error for user {user_id}, attempting token refresh (attempt {attempt + 1})")
                    
                    # Try to refresh the token
                    if _refresh_hubspot_token_sync(user_id, session):
                        logger.info(f"✅ Token refresh successful for user {user_id}, retrying sync")
                        # Close the current service before retrying
                        try:
                            hubspot_service.close_sync()
                        except:
                            pass
                        continue  # Retry with new token
                    else:
                        logger.error(f"❌ Token refresh failed for user {user_id}")
                        raise Exception(f"Failed to refresh HubSpot token for user {user_id}")
                else:
                    # Not a 401 error or we've exhausted retry attempts
                    hubspot_service.close_sync()
                    raise e
    
    # If we get here, we've exhausted all retry attempts
    raise Exception(f"HubSpot contacts sync failed after {max_token_refresh_attempts} attempts for user {user_id}")

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
        error_str = str(e).lower()
        logger.error(f"HubSpot deals sync failed for user {user_id}: {str(e)}")
        
        # Check if this is a 401 error and we should try to refresh token
        if "401" in error_str:
            logger.warning(f"🔄 Detected 401 error in HubSpot deals sync, user {user_id} needs token refresh")
            
            # Try to refresh token before retrying
            try:
                with SyncSessionLocal() as session:
                    if _refresh_hubspot_token_sync(user_id, session):
                        logger.info(f"✅ Token refreshed successfully for user {user_id}, task will retry")
                    else:
                        logger.error(f"❌ Token refresh failed for user {user_id}")
            except Exception as refresh_error:
                logger.error(f"❌ Token refresh error for user {user_id}: {str(refresh_error)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_hubspot_deals_sync(user_id: str) -> Dict[str, Any]:
    """Sync implementation of HubSpot deals sync"""
    max_token_refresh_attempts = 2
    
    for attempt in range(max_token_refresh_attempts):
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
            
            try:
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
                hubspot_service.close_sync()
                
                return {
                    "user_id": user_id,
                    "total_deals": len(all_deals),
                    "new_deals": len(new_deals),
                    "processed_count": processed_count,
                    "synced_at": datetime.utcnow().isoformat()
                }
                
            except Exception as e:
                error_str = str(e).lower()
                
                # Check if this is a 401 error and we haven't exhausted retry attempts
                if "401" in error_str and attempt < max_token_refresh_attempts - 1:
                    logger.warning(f"🔄 HubSpot 401 error for user {user_id}, attempting token refresh (attempt {attempt + 1})")
                    
                    # Try to refresh the token
                    if _refresh_hubspot_token_sync(user_id, session):
                        logger.info(f"✅ Token refresh successful for user {user_id}, retrying sync")
                        # Close the current service before retrying
                        try:
                            hubspot_service.close_sync()
                        except:
                            pass
                        continue  # Retry with new token
                    else:
                        logger.error(f"❌ Token refresh failed for user {user_id}")
                        raise Exception(f"Failed to refresh HubSpot token for user {user_id}")
                else:
                    # Not a 401 error or we've exhausted retry attempts
                    hubspot_service.close_sync()
                    raise e
    
    # If we get here, we've exhausted all retry attempts
    raise Exception(f"HubSpot deals sync failed after {max_token_refresh_attempts} attempts for user {user_id}")

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
        error_str = str(e).lower()
        logger.error(f"HubSpot companies sync failed for user {user_id}: {str(e)}")
        
        # Check if this is a 401 error and we should try to refresh token
        if "401" in error_str:
            logger.warning(f"🔄 Detected 401 error in HubSpot companies sync, user {user_id} needs token refresh")
            
            # Try to refresh token before retrying
            try:
                with SyncSessionLocal() as session:
                    if _refresh_hubspot_token_sync(user_id, session):
                        logger.info(f"✅ Token refreshed successfully for user {user_id}, task will retry")
                    else:
                        logger.error(f"❌ Token refresh failed for user {user_id}")
            except Exception as refresh_error:
                logger.error(f"❌ Token refresh error for user {user_id}: {str(refresh_error)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_hubspot_companies_sync(user_id: str) -> Dict[str, Any]:
    """Sync implementation of HubSpot companies sync"""
    max_token_refresh_attempts = 2
    
    for attempt in range(max_token_refresh_attempts):
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
            
            try:
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
                hubspot_service.close_sync()
                
                return {
                    "user_id": user_id,
                    "total_companies": len(all_companies),
                    "new_companies": len(new_companies),
                    "processed_count": processed_count,
                    "synced_at": datetime.utcnow().isoformat()
                }
                
            except Exception as e:
                error_str = str(e).lower()
                
                # Check if this is a 401 error and we haven't exhausted retry attempts
                if "401" in error_str and attempt < max_token_refresh_attempts - 1:
                    logger.warning(f"🔄 HubSpot 401 error for user {user_id}, attempting token refresh (attempt {attempt + 1})")
                    
                    # Try to refresh the token
                    if _refresh_hubspot_token_sync(user_id, session):
                        logger.info(f"✅ Token refresh successful for user {user_id}, retrying sync")
                        # Close the current service before retrying
                        try:
                            hubspot_service.close_sync()
                        except:
                            pass
                        continue  # Retry with new token
                    else:
                        logger.error(f"❌ Token refresh failed for user {user_id}")
                        raise Exception(f"Failed to refresh HubSpot token for user {user_id}")
                else:
                    # Not a 401 error or we've exhausted retry attempts
                    hubspot_service.close_sync()
                    raise e
    
    # If we get here, we've exhausted all retry attempts
    raise Exception(f"HubSpot companies sync failed after {max_token_refresh_attempts} attempts for user {user_id}")

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
    
    # Add type
    if company.type:
        parts.append(f"Type: {company.type}")
    
    # Add description
    if company.description:
        # Truncate very long descriptions
        description = company.description[:1000] if len(company.description) > 1000 else company.description
        parts.append(f"Description: {description}")
    
    # Add contact info
    if company.phone:
        parts.append(f"Phone: {company.phone}")
    
    # Add location info
    location_parts = []
    if company.city:
        location_parts.append(company.city)
    if company.state:
        location_parts.append(company.state)
    if company.country:
        location_parts.append(company.country)
    if location_parts:
        parts.append(f"Location: {', '.join(location_parts)}")
    
    # Add financial info
    if company.num_employees:
        parts.append(f"Employees: {company.num_employees}")
    if company.annualrevenue:
        parts.append(f"Annual Revenue: ${company.annualrevenue:,.2f}")
    
    return "\n".join(parts)

@celery_app.task(bind=True, max_retries=3)
def sync_all_users_hubspot(self):
    """Sync HubSpot data for all users with HubSpot OAuth"""
    try:
        logger.info("Starting HubSpot sync for all users")
        
        # Run sync function
        result = _sync_all_users_hubspot_sync()
        
        logger.info(f"All users HubSpot sync completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"All users HubSpot sync failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _sync_all_users_hubspot_sync() -> Dict[str, Any]:
    """Sync implementation of syncing all users' HubSpot data"""
    with SyncSessionLocal() as session:
        # Get all users with HubSpot OAuth tokens
        result = session.execute(
            select(User).where(User.hubspot_access_token.is_not(None))
        )
        users = result.scalars().all()
        
        sync_results = []
        
        for user in users:
            try:
                # Schedule individual sync for all HubSpot data
                sync_result = sync_all_hubspot_data.delay(user.id)
                sync_results.append({
                    "user_id": user.id,
                    "task_id": sync_result.id,
                    "status": "scheduled"
                })
                
            except Exception as e:
                logger.error(f"Failed to schedule HubSpot sync for user {user.id}: {str(e)}")
                sync_results.append({
                    "user_id": user.id,
                    "status": "failed",
                    "error": str(e)
                })
        
        return {
            "total_users": len(users),
            "scheduled_syncs": len([r for r in sync_results if r["status"] == "scheduled"]),
            "failed_syncs": len([r for r in sync_results if r["status"] == "failed"]),
            "sync_results": sync_results,
            "synced_at": datetime.utcnow().isoformat()
        } 

@celery_app.task(bind=True, max_retries=3)
def send_thank_you_emails_to_new_contacts(self, user_id: str = None):
    """Send thank you emails to new HubSpot contacts who haven't received them yet"""
    try:
        logger.info(f"Starting thank you email sending for new HubSpot contacts")
        
        # Run sync function
        result = _send_thank_you_emails_sync(user_id)
        
        logger.info(f"Thank you email sending completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Thank you email sending failed: {str(e)}")
        
        # Retry with exponential backoff
        if self.request.retries < self.max_retries:
            retry_delay = 2 ** self.request.retries
            raise self.retry(countdown=retry_delay, exc=e)
        else:
            raise e

def _send_thank_you_emails_sync(user_id: str = None) -> Dict[str, Any]:
    """Sync implementation of sending thank you emails to new contacts"""
    with SyncSessionLocal() as session:
        # Build query for users to process
        if user_id:
            # Process specific user
            result = session.execute(
                select(User).where(
                    User.id == user_id,
                    User.hubspot_access_token.is_not(None),
                    User.google_access_token.is_not(None)  # Need Gmail to send emails
                )
            )
            users = result.scalars().all()
        else:
            # Process all users with both HubSpot and Gmail access
            result = session.execute(
                select(User).where(
                    User.hubspot_access_token.is_not(None),
                    User.google_access_token.is_not(None)
                )
            )
            users = result.scalars().all()
        
        total_emails_sent = 0
        total_contacts_processed = 0
        errors = []
        
        for user in users:
            try:
                # Get contacts that need thank you emails
                contacts_result = session.execute(
                    select(HubspotContact).where(
                        HubspotContact.user_id == user.id,
                        HubspotContact.thank_you_email_sent == False,
                        HubspotContact.email.is_not(None),
                        HubspotContact.email != "",
                        # Exclude appointment scheduling contacts from thank you emails
                        HubspotContact.contact_creation_context != "appointment_scheduling"
                    ).order_by(HubspotContact.created_at.desc())
                )
                contacts_needing_emails = contacts_result.scalars().all()
                
                if not contacts_needing_emails:
                    logger.info(f"No new contacts need thank you emails for user {user.email}")
                    continue
                
                logger.info(f"Found {len(contacts_needing_emails)} contacts needing thank you emails for user {user.email}")
                
                for contact in contacts_needing_emails:
                    try:
                        # Send thank you email
                        email_sent = _send_thank_you_email_to_contact(user, contact)
                        
                        if email_sent:
                            # Mark as sent
                            contact.thank_you_email_sent = True
                            contact.thank_you_email_sent_at = datetime.utcnow()
                            total_emails_sent += 1
                            logger.info(f"✅ Thank you email sent to {contact.email}")
                        else:
                            logger.warning(f"⚠️ Failed to send thank you email to {contact.email}")
                        
                        total_contacts_processed += 1
                        
                        # Commit in batches to avoid long transactions
                        if total_contacts_processed % 5 == 0:
                            session.commit()
                            
                    except Exception as contact_error:
                        error_msg = f"Failed to process contact {contact.email} for user {user.email}: {str(contact_error)}"
                        errors.append(error_msg)
                        logger.error(error_msg)
                        continue
                
                # Final commit for this user
                session.commit()
                logger.info(f"✅ Processed {len(contacts_needing_emails)} contacts for user {user.email}")
                
            except Exception as user_error:
                error_msg = f"Failed to process thank you emails for user {user.email}: {str(user_error)}"
                errors.append(error_msg)
                logger.error(error_msg)
                continue
        
        result = {
            "users_processed": len(users),
            "contacts_processed": total_contacts_processed,
            "emails_sent": total_emails_sent,
            "errors": errors,
            "processed_at": datetime.utcnow().isoformat()
        }
        
        logger.info(f"✅ Thank you email sending completed: {result}")
        return result

def _send_thank_you_email_to_contact(user: User, contact: HubspotContact) -> bool:
    """Send a thank you email to a specific contact"""
    try:
        # Build personalized email content
        contact_name = _get_contact_display_name(contact)
        
        subject = "Thank you for being a customer"
        body = f"Hello {contact_name},\n\nThank you for being a customer."
        
        # Use existing email sending infrastructure
        from tasks.gmail_tasks import _send_email_sync
        
        result = _send_email_sync(
            user_id=user.id,
            to=contact.email,
            subject=subject,
            body=body
        )
        
        return bool(result and result.get("message_id"))
        
    except Exception as e:
        logger.error(f"Failed to send thank you email to {contact.email}: {str(e)}")
        return False

def _get_contact_display_name(contact: HubspotContact) -> str:
    """Get a nice display name for the contact"""
    if contact.firstname and contact.lastname:
        return f"{contact.firstname} {contact.lastname}"
    elif contact.firstname:
        return contact.firstname
    elif contact.lastname:
        return contact.lastname
    elif contact.email:
        # Extract name from email if available
        name_part = contact.email.split('@')[0]
        # Convert dots and underscores to spaces and title case
        return name_part.replace('.', ' ').replace('_', ' ').title()
    else:
        return "Valued Customer" 