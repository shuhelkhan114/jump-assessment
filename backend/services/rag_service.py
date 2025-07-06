from typing import List, Dict, Any, Optional, Tuple
import structlog
from sqlalchemy import text, select
from database import AsyncSessionLocal, Email, HubspotContact, HubspotDeal, HubspotCompany
from services.openai_service import openai_service

logger = structlog.get_logger()

class RAGService:
    def __init__(self):
        self.max_context_items = 5
        self.similarity_threshold = 0.2  # Lower threshold for better results
    
    async def search_emails(self, query_embedding: List[float], user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant emails using vector similarity"""
        try:
            async with AsyncSessionLocal() as session:
                # Vector similarity search query
                similarity_query = text("""
                    SELECT id, subject, content, sender, recipient, received_at, 
                           (1 - (embedding <=> :query_embedding)) AS similarity
                    FROM emails 
                    WHERE user_id = :user_id 
                      AND embedding IS NOT NULL
                      AND (1 - (embedding <=> :query_embedding)) > :threshold
                    ORDER BY similarity DESC
                    LIMIT :limit
                """)
                
                result = await session.execute(
                    similarity_query,
                    {
                        "query_embedding": str(query_embedding),
                        "user_id": user_id,
                        "threshold": self.similarity_threshold,
                        "limit": limit
                    }
                )
                
                emails = []
                for row in result:
                    emails.append({
                        "id": row.id,
                        "type": "email",
                        "subject": row.subject,
                        "content": row.content[:500] if row.content else "",  # Truncate for context
                        "sender": row.sender,
                        "recipient": row.recipient,
                        "received_at": row.received_at.isoformat() if row.received_at else None,
                        "similarity": float(row.similarity)
                    })
                
                logger.info(f"Found {len(emails)} relevant emails for user {user_id}")
                return emails
                
        except Exception as e:
            logger.error(f"Failed to search emails: {str(e)}")
            return []
    
    async def search_contacts(self, query_embedding: List[float], user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant HubSpot contacts using vector similarity"""
        try:
            async with AsyncSessionLocal() as session:
                # Vector similarity search query
                similarity_query = text("""
                    SELECT id, firstname, lastname, email, phone, company, jobtitle, industry,
                           (1 - (embedding <=> :query_embedding)) AS similarity
                    FROM hubspot_contacts 
                    WHERE user_id = :user_id 
                      AND embedding IS NOT NULL
                      AND (1 - (embedding <=> :query_embedding)) > :threshold
                    ORDER BY similarity DESC
                    LIMIT :limit
                """)
                
                result = await session.execute(
                    similarity_query,
                    {
                        "query_embedding": str(query_embedding),
                        "user_id": user_id,
                        "threshold": self.similarity_threshold,
                        "limit": limit
                    }
                )
                
                contacts = []
                for row in result:
                    name = f"{row.firstname or ''} {row.lastname or ''}".strip()
                    contacts.append({
                        "id": row.id,
                        "type": "contact",
                        "name": name or "Unknown",
                        "email": row.email,
                        "phone": row.phone,
                        "company": row.company,
                        "jobtitle": row.jobtitle,
                        "industry": row.industry,
                        "similarity": float(row.similarity)
                    })
                
                logger.info(f"Found {len(contacts)} relevant contacts for user {user_id}")
                return contacts
                
        except Exception as e:
            logger.error(f"Failed to search contacts: {str(e)}")
            return []
    
    async def search_deals(self, query_embedding: List[float], user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant HubSpot deals using vector similarity"""
        try:
            async with AsyncSessionLocal() as session:
                # Vector similarity search query
                similarity_query = text("""
                    SELECT id, dealname, amount, dealstage, pipeline, description, closedate,
                           (1 - (embedding <=> :query_embedding)) AS similarity
                    FROM hubspot_deals 
                    WHERE user_id = :user_id 
                      AND embedding IS NOT NULL
                      AND (1 - (embedding <=> :query_embedding)) > :threshold
                    ORDER BY similarity DESC
                    LIMIT :limit
                """)
                
                result = await session.execute(
                    similarity_query,
                    {
                        "query_embedding": str(query_embedding),
                        "user_id": user_id,
                        "threshold": self.similarity_threshold,
                        "limit": limit
                    }
                )
                
                deals = []
                for row in result:
                    deals.append({
                        "id": row.id,
                        "type": "deal",
                        "dealname": row.dealname,
                        "amount": row.amount,
                        "dealstage": row.dealstage,
                        "pipeline": row.pipeline,
                        "description": row.description[:300] if row.description else None,
                        "closedate": row.closedate.isoformat() if row.closedate else None,
                        "similarity": float(row.similarity)
                    })
                
                logger.info(f"Found {len(deals)} relevant deals for user {user_id}")
                return deals
                
        except Exception as e:
            logger.error(f"Failed to search deals: {str(e)}")
            return []
    
    async def search_companies(self, query_embedding: List[float], user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant HubSpot companies using vector similarity"""
        try:
            async with AsyncSessionLocal() as session:
                # Vector similarity search query
                similarity_query = text("""
                    SELECT id, name, domain, industry, description, city, state, num_employees, annualrevenue,
                           (1 - (embedding <=> :query_embedding)) AS similarity
                    FROM hubspot_companies 
                    WHERE user_id = :user_id 
                      AND embedding IS NOT NULL
                      AND (1 - (embedding <=> :query_embedding)) > :threshold
                    ORDER BY similarity DESC
                    LIMIT :limit
                """)
                
                result = await session.execute(
                    similarity_query,
                    {
                        "query_embedding": str(query_embedding),
                        "user_id": user_id,
                        "threshold": self.similarity_threshold,
                        "limit": limit
                    }
                )
                
                companies = []
                for row in result:
                    companies.append({
                        "id": row.id,
                        "type": "company",
                        "name": row.name,
                        "domain": row.domain,
                        "industry": row.industry,
                        "description": row.description[:300] if row.description else None,
                        "location": f"{row.city or ''}, {row.state or ''}".strip(', '),
                        "num_employees": row.num_employees,
                        "annualrevenue": row.annualrevenue,
                        "similarity": float(row.similarity)
                    })
                
                logger.info(f"Found {len(companies)} relevant companies for user {user_id}")
                return companies
                
        except Exception as e:
            logger.error(f"Failed to search companies: {str(e)}")
            return []
    
    async def get_context_for_query(self, query: str, user_id: str, max_results: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
        """Get relevant context for a user query using RAG"""
        try:
            # Generate embedding for the query
            query_embedding = await openai_service.generate_embedding(query)
            
            if not query_embedding:
                logger.warning("Failed to generate query embedding")
                return "", []
            
            # Search across all data types
            emails = await self.search_emails(query_embedding, user_id, limit=3)
            contacts = await self.search_contacts(query_embedding, user_id, limit=3)
            deals = await self.search_deals(query_embedding, user_id, limit=2)
            companies = await self.search_companies(query_embedding, user_id, limit=2)
            
            # Combine and sort by similarity
            all_results = emails + contacts + deals + companies
            all_results.sort(key=lambda x: x["similarity"], reverse=True)
            
            # Take top results
            top_results = all_results[:max_results]
            
            # Build context string
            context = self._build_context_string(top_results)
            
            logger.info(f"Generated context with {len(top_results)} items for query: {query[:50]}...")
            return context, top_results
            
        except Exception as e:
            logger.error(f"Failed to get context for query: {str(e)}")
            return "", []
    
    def _build_context_string(self, results: List[Dict[str, Any]]) -> str:
        """Build a context string from search results"""
        if not results:
            return ""
        
        context_parts = []
        
        for item in results:
            if item["type"] == "email":
                context_parts.append(
                    f"📧 Email from {item['sender']} - Subject: {item['subject']}\n"
                    f"Content: {item['content']}\n"
                    f"Date: {item['received_at']}"
                )
            elif item["type"] == "contact":
                job_info = f" ({item['jobtitle']})" if item['jobtitle'] else ""
                company_info = f" at {item['company']}" if item['company'] else ""
                context_parts.append(
                    f"👤 Contact: {item['name']}{job_info}{company_info}\n"
                    f"Email: {item['email']}\n"
                    f"Phone: {item['phone'] or 'Not provided'}\n"
                    f"Industry: {item['industry'] or 'Not specified'}"
                )
            elif item["type"] == "deal":
                amount_info = f" (${item['amount']:,.2f})" if item['amount'] else ""
                context_parts.append(
                    f"💼 Deal: {item['dealname']}{amount_info}\n"
                    f"Stage: {item['dealstage']} in {item['pipeline']}\n"
                    f"Description: {item['description'] or 'No description'}\n"
                    f"Close Date: {item['closedate'] or 'Not set'}"
                )
            elif item["type"] == "company":
                size_info = f" ({item['num_employees']} employees)" if item['num_employees'] else ""
                revenue_info = f" - ${item['annualrevenue']:,.0f} revenue" if item['annualrevenue'] else ""
                context_parts.append(
                    f"🏢 Company: {item['name']}{size_info}{revenue_info}\n"
                    f"Industry: {item['industry'] or 'Not specified'}\n"
                    f"Location: {item['location'] or 'Not specified'}\n"
                    f"Website: {item['domain'] or 'Not provided'}\n"
                    f"Description: {item['description'] or 'No description'}"
                )
        
        return "\n\n---\n\n".join(context_parts)
    
    async def store_email_embedding(self, email_id: str, content: str) -> bool:
        """Generate and store embedding for an email"""
        try:
            # Combine subject and body for embedding
            embedding = await openai_service.generate_embedding(content)
            
            if not embedding:
                return False
            
            async with AsyncSessionLocal() as session:
                # Update email with embedding
                update_query = text("""
                    UPDATE emails 
                    SET embedding = :embedding 
                    WHERE id = :email_id
                """)
                
                await session.execute(
                    update_query,
                    {
                        "embedding": str(embedding),
                        "email_id": email_id
                    }
                )
                await session.commit()
                
                logger.info(f"Stored embedding for email {email_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to store email embedding: {str(e)}")
            return False
    
    async def store_contact_embedding(self, contact_id: str, content: str) -> bool:
        """Generate and store embedding for a contact"""
        try:
            embedding = await openai_service.generate_embedding(content)
            
            if not embedding:
                return False
            
            async with AsyncSessionLocal() as session:
                # Update contact with embedding
                update_query = text("""
                    UPDATE hubspot_contacts 
                    SET embedding = :embedding 
                    WHERE id = :contact_id
                """)
                
                await session.execute(
                    update_query,
                    {
                        "embedding": str(embedding),
                        "contact_id": contact_id
                    }
                )
                await session.commit()
                
                logger.info(f"Stored embedding for contact {contact_id}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to store contact embedding: {str(e)}")
            return False

# Global instance
rag_service = RAGService() 