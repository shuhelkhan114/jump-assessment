"""
HubSpot API service for fetching and processing CRM data
"""
import os
from typing import List, Dict, Optional, Any
from datetime import datetime
import structlog
import httpx
from urllib.parse import urlencode

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
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
            
            logger.info("HubSpot service initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize HubSpot service: {str(e)}")
            return False
    
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
            response = await self.client.get(
                "/crm/v3/objects/contacts",
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Retrieved {len(data.get('results', []))} contacts from HubSpot")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"HubSpot API request failed: {str(e)}")
            raise
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
            response = await self.client.get(
                "/crm/v3/objects/deals",
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Retrieved {len(data.get('results', []))} deals from HubSpot")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"HubSpot API request failed: {str(e)}")
            raise
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
            response = await self.client.get(
                "/crm/v3/objects/companies",
                params=params
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Retrieved {len(data.get('results', []))} companies from HubSpot")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"HubSpot API request failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to get companies: {str(e)}")
            raise
    
    async def create_contact(self, contact_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new contact in HubSpot"""
        try:
            if not self.client:
                raise Exception("HubSpot service not initialized")
            
            # Format contact data for HubSpot API
            formatted_data = {
                "properties": contact_data
            }
            
            # Make API request
            response = await self.client.post(
                "/crm/v3/objects/contacts",
                json=formatted_data
            )
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"Created contact in HubSpot: {data.get('id')}")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"HubSpot API request failed: {str(e)}")
            raise
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
            response = await self.client.patch(
                f"/crm/v3/objects/contacts/{contact_id}",
                json=formatted_data
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Updated contact in HubSpot: {contact_id}")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"HubSpot API request failed: {str(e)}")
            raise
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
            response = await self.client.post(
                "/crm/v3/objects/deals",
                json=formatted_data
            )
            
            if response.status_code == 201:
                data = response.json()
                logger.info(f"Created deal in HubSpot: {data.get('id')}")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"HubSpot API request failed: {str(e)}")
            raise
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
            response = await self.client.post(
                "/crm/v3/objects/contacts/search",
                json=search_data
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Found {len(data.get('results', []))} contacts matching: {search_term}")
                return data
            else:
                logger.error(f"HubSpot API error: {response.status_code} - {response.text}")
                raise Exception(f"HubSpot API error: {response.status_code}")
                
        except httpx.RequestError as e:
            logger.error(f"HubSpot API request failed: {str(e)}")
            raise
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
            response = await self.client.post(
                "/crm/v3/objects/contacts/search",
                json=search_data
            )
            
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
                
        except httpx.RequestError as e:
            logger.error(f"HubSpot API request failed: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Failed to get contact by email: {str(e)}")
            raise
    
    async def close(self):
        """Close the HTTP client"""
        if self.client:
            await self.client.aclose()

# Global service instance
hubspot_service = HubSpotService() 