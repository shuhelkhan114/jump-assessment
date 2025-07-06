from typing import List, Dict, Any, Optional, Tuple
import structlog
from sqlalchemy import text, select
from database import AsyncSessionLocal, Email, HubspotContact
from services.openai_service import openai_service

logger = structlog.get_logger()

class RAGService:
    def __init__(self):
        self.max_context_items = 5
        self.similarity_threshold = 0.7
    
    async def search_emails(self, query_embedding: List[float], user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant emails using vector similarity"""
        try:
            async with AsyncSessionLocal() as session:
                # Vector similarity search query
                similarity_query = text("""
                    SELECT id, subject, body, sender, recipient, date, 
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
                        "body": row.body[:500],  # Truncate for context
                        "sender": row.sender,
                        "recipient": row.recipient,
                        "date": row.date.isoformat() if row.date else None,
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
                    SELECT id, name, email, phone, company, notes,
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
                    contacts.append({
                        "id": row.id,
                        "type": "contact",
                        "name": row.name,
                        "email": row.email,
                        "phone": row.phone,
                        "company": row.company,
                        "notes": row.notes[:300] if row.notes else None,  # Truncate for context
                        "similarity": float(row.similarity)
                    })
                
                logger.info(f"Found {len(contacts)} relevant contacts for user {user_id}")
                return contacts
                
        except Exception as e:
            logger.error(f"Failed to search contacts: {str(e)}")
            return []
    
    async def get_context_for_query(self, query: str, user_id: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Get relevant context for a user query using RAG"""
        try:
            # Generate embedding for the query
            query_embedding = await openai_service.generate_embedding(query)
            
            if not query_embedding:
                logger.warning("Failed to generate query embedding")
                return "", []
            
            # Search both emails and contacts
            emails = await self.search_emails(query_embedding, user_id, limit=3)
            contacts = await self.search_contacts(query_embedding, user_id, limit=2)
            
            # Combine and sort by similarity
            all_results = emails + contacts
            all_results.sort(key=lambda x: x["similarity"], reverse=True)
            
            # Take top results
            top_results = all_results[:self.max_context_items]
            
            # Build context string
            context_parts = []
            
            for item in top_results:
                if item["type"] == "email":
                    context_parts.append(
                        f"Email from {item['sender']} - Subject: {item['subject']}\n"
                        f"Content: {item['body']}\n"
                        f"Date: {item['date']}"
                    )
                elif item["type"] == "contact":
                    context_parts.append(
                        f"Contact: {item['name']} ({item['email']})\n"
                        f"Company: {item['company']}\n"
                        f"Notes: {item['notes'] or 'No notes available'}"
                    )
            
            context = "\n\n---\n\n".join(context_parts) if context_parts else ""
            
            logger.info(f"Generated context with {len(top_results)} items for query: {query[:50]}...")
            return context, top_results
            
        except Exception as e:
            logger.error(f"Failed to get context for query: {str(e)}")
            return "", []
    
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