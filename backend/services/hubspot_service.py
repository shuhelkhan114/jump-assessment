"""
HubSpot API service for fetching and processing CRM data
"""
import os
from typing import List, Dict, Optional, Any
from datetime import datetime
import structlog
import httpx
from urllib.parse import urlencode
import asyncio

logger = structlog.get_logger()

class HubSpotService:
    """HubSpot API service for CRM operations"""
    
    def __init__(self):
        self.client = None
        self.access_token = None
        self.base_url = "https://api.hubapi.com"
    
    def initialize_service(self, access_token: str) -> bool:
        """Initialize HubSpot service with OAuth token"""
        try:
            self.access_token = access_token
            
            # Enhanced client configuration with better timeout and retry settings
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=httpx.Timeout(30.0, connect=10.0, read=30.0, write=10.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                follow_redirects=True
            )
            
            logger.info("HubSpot service initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize HubSpot service: {str(e)}")
            return False
    
    async def _make_request_with_retry(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Make HTTP request with retry logic for network issues"""
        max_retries = 3
        base_delay = 1.0
        
        for attempt in range(max_retries):
            try:
                if method.upper() == "GET":
                    response = await self.client.get(endpoint, **kwargs)
                elif method.upper() == "POST":
                    response = await self.client.post(endpoint, **kwargs)
                elif method.upper() == "PUT":
                    response = await self.client.put(endpoint, **kwargs)
                elif method.upper() == "PATCH":
                    response = await self.client.patch(endpoint, **kwargs)
                elif method.upper() == "DELETE":
                    response = await self.client.delete(endpoint, **kwargs)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                return response
                
            except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadTimeout) as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(f"Network error on attempt {attempt + 1}/{max_retries}: {str(e)}. Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.error(f"Network error after {max_retries} attempts: {str(e)}")
                    raise Exception(f"HubSpot API unavailable after {max_retries} attempts. Please check your internet connection and try again later.")
            except httpx.RequestError as e:
                logger.error(f"HubSpot request error: {str(e)}")
                raise Exception(f"HubSpot API request failed: {str(e)}")
            except Exception as e:
                logger.error(f"Unexpected error in HubSpot request: {str(e)}")
                raise
    
    async def get_contacts(self, limit: int = 100, after: Optional[str] = None) -> Dict[str, Any]:
        """Get contacts from HubSpot CRM"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Define properties to fetch
            properties = [
                "firstname", "lastname", "email", "phone", "company", 
                "jobtitle", "industry", "lifecyclestage", "lead_status",
                "notes_last_contacted", "notes_last_activity_date",
                "num_notes", "createdate", "lastmodifieddate"
            ]
            
            # Build query parameters
            params = {
                "limit": limit,
                "properties": ",".join(properties),
                "paginateAssociations": "false",
                "archived": "false"
            }
            
            if after:
                params["after"] = after
            
            # Make API request
            response = await self._make_request_with_retry("GET", "/crm/v3/objects/contacts", params=params)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Retrieved {len(data.get('results', []))} contacts from HubSpot")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to get contacts: {str(e)}")
            raise
    
    async def get_deals(self, limit: int = 100, after: Optional[str] = None) -> Dict[str, Any]:
        """Get deals from HubSpot CRM"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Define properties to fetch
            properties = [
                "dealname", "amount", "dealstage", "pipeline", "closedate",
                "createdate", "lastmodifieddate", "dealtype", "description",
                "notes_last_contacted", "notes_last_activity_date",
                "num_notes", "hubspot_owner_id"
            ]
            
            # Build query parameters
            params = {
                "limit": limit,
                "properties": ",".join(properties),
                "paginateAssociations": "false",
                "archived": "false"
            }
            
            if after:
                params["after"] = after
            
            # Make API request
            response = await self._make_request_with_retry("GET", "/crm/v3/objects/deals", params=params)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Retrieved {len(data.get('results', []))} deals from HubSpot")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to get deals: {str(e)}")
            raise
    
    async def get_companies(self, limit: int = 100, after: Optional[str] = None) -> Dict[str, Any]:
        """Get companies from HubSpot CRM"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Define properties to fetch
            properties = [
                "name", "domain", "industry", "type", "description",
                "phone", "address", "city", "state", "country",
                "num_employees", "annualrevenue", "createdate",
                "lastmodifieddate", "notes_last_contacted",
                "notes_last_activity_date", "num_notes"
            ]
            
            # Build query parameters
            params = {
                "limit": limit,
                "properties": ",".join(properties),
                "paginateAssociations": "false",
                "archived": "false"
            }
            
            if after:
                params["after"] = after
            
            # Make API request
            response = await self._make_request_with_retry("GET", "/crm/v3/objects/companies", params=params)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Retrieved {len(data.get('results', []))} companies from HubSpot")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to get companies: {str(e)}")
            raise
    
    async def create_contact(self, contact_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new contact in HubSpot (or return existing if already exists)"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Format contact data for HubSpot API
            formatted_data = {
                "properties": contact_data
            }
            
            # Make API request
            response = await self._make_request_with_retry("POST", "/crm/v3/objects/contacts", json=formatted_data)
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"Created contact in HubSpot: {data.get('id')}")
                return data
            elif response.status_code == 409:
                # Contact already exists, try to get existing contact
                logger.info(f"Contact already exists, finding existing contact")
                try:
                    # Parse the error response to get existing contact ID
                    error_data = response.json()
                    if "Existing ID:" in error_data.get("message", ""):
                        existing_id = error_data["message"].split("Existing ID: ")[1].split('"')[0]
                        logger.info(f"Found existing contact ID: {existing_id}")
                        
                        # Get the existing contact details
                        get_response = await self._make_request_with_retry("GET", f"/crm/v3/objects/contacts/{existing_id}", params={"properties": "firstname,lastname,email,phone,company,jobtitle,industry,lifecyclestage"})
                        
                        if get_response.status_code == 200:
                            existing_contact = get_response.json()
                            logger.info(f"Retrieved existing contact: {existing_contact.get('id')}")
                            return {
                                **existing_contact,
                                "_status": "existing",
                                "_message": "Contact already exists in HubSpot"
                            }
                    
                    # If we can't parse the ID, try to search by email
                    if "email" in contact_data:
                        existing_contact = await self.get_contact_by_email(contact_data["email"])
                        if existing_contact:
                            logger.info(f"Found existing contact by email: {existing_contact.get('id')}")
                            return {
                                **existing_contact,
                                "_status": "existing",
                                "_message": "Contact already exists in HubSpot"
                            }
                    
                    # If we still can't find the contact, return the error info
                    logger.warning(f"Contact exists but couldn't retrieve details: {error_data}")
                    return {
                        "_status": "conflict",
                        "_message": f"Contact already exists in HubSpot: {error_data.get('message', 'Unknown conflict')}"
                    }
                
                except Exception as parse_error:
                    logger.error(f"Error parsing existing contact: {str(parse_error)}")
                    return {
                        "_status": "conflict",
                        "_message": "Contact already exists in HubSpot but couldn't retrieve details"
                    }
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to create contact: {str(e)}")
            raise
    
    async def update_contact(self, contact_id: str, contact_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing contact in HubSpot"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Format contact data for HubSpot API
            formatted_data = {
                "properties": contact_data
            }
            
            # Make API request
            response = await self._make_request_with_retry("PATCH", f"/crm/v3/objects/contacts/{contact_id}", json=formatted_data)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Updated contact in HubSpot: {contact_id}")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to update contact: {str(e)}")
            raise
    
    async def create_deal(self, deal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new deal in HubSpot"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Format deal data for HubSpot API
            formatted_data = {
                "properties": deal_data
            }
            
            # Make API request
            response = await self._make_request_with_retry("POST", "/crm/v3/objects/deals", json=formatted_data)
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"Created deal in HubSpot: {data.get('id')}")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to create deal: {str(e)}")
            raise
    
    async def search_contacts(self, search_term: str, limit: int = 50) -> Dict[str, Any]:
        """Search contacts in HubSpot"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Build search request
            search_data = {
                "query": search_term,
                "limit": limit,
                "properties": [
                    "firstname", "lastname", "email", "phone", "company",
                    "jobtitle", "industry", "lifecyclestage"
                ]
            }
            
            # Make API request
            response = await self._make_request_with_retry("POST", "/crm/v3/objects/contacts/search", json=search_data)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Found {len(data.get('results', []))} contacts matching: {search_term}")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to search contacts: {str(e)}")
            raise
    
    async def get_contact_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get contact by email address"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Search for contact by email
            search_data = {
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "email",
                                "operator": "EQ",
                                "value": email
                            }
                        ]
                    }
                ],
                "properties": [
                    "firstname", "lastname", "email", "phone", "company",
                    "jobtitle", "industry", "lifecyclestage"
                ]
            }
            
            # Make API request
            response = await self._make_request_with_retry("POST", "/crm/v3/objects/contacts/search", json=search_data)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('results', [])
                if results:
                    logger.info(f"Found contact with email: {email}")
                    return results[0]
                else:
                    logger.info(f"No contact found with email: {email}")
                    return None
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"Failed to get contact by email: {str(e)}")
            raise
    
    async def close(self):
        """Close the HTTP client"""
        if self.client:
            await self.client.aclose()
    
    def close_sync(self):
        """Close the HTTP client synchronously (for Celery tasks)"""
        if self.client:
            try:
                # Try to close gracefully
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # If loop is running, schedule close
                        loop.create_task(self.client.aclose())
                    else:
                        # If loop is not running, run it
                        asyncio.run(self.client.aclose())
                except RuntimeError:
                    # Event loop is closed, just set client to None
                    self.client = None
            except Exception:
                # If all else fails, just set client to None
                self.client = None

# Global service instance
hubspot_service = HubSpotService() 