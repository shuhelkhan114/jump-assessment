from typing import List, Dict, Any, Optional, Tuple
import structlog
from datetime import datetime
from sqlalchemy import text, select
from database import AsyncSessionLocal, Email, HubspotContact, HubspotDeal, HubspotCompany, CalendarEvent
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

    async def search_calendar_events(self, query_embedding: List[float], user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for relevant calendar events using vector similarity"""
        try:
            async with AsyncSessionLocal() as session:
                # Vector similarity search query
                similarity_query = text("""
                    SELECT id, title, description, location, start_datetime, end_datetime, 
                           start_date, end_date, is_all_day, organizer_name, organizer_email, attendees,
                           (1 - (embedding <=> :query_embedding)) AS similarity
                    FROM calendar_events 
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
                
                events = []
                for row in result:
                    # Format datetime for display (these are stored as UTC, frontend will convert to local time)
                    if row.start_datetime:
                        start_display = row.start_datetime.strftime("%B %d, %Y at %I:%M %p")
                    elif row.start_date:
                        start_display = f"{row.start_date} (all day)"
                    else:
                        start_display = "Date not specified"
                    
                    if row.end_datetime:
                        end_display = row.end_datetime.strftime("%B %d, %Y at %I:%M %p")
                    elif row.end_date:
                        end_display = f"{row.end_date} (all day)"
                    else:
                        end_display = "End date not specified"
                    
                    # Parse attendees JSON if available
                    attendees_list = []
                    if row.attendees:
                        try:
                            import json
                            attendees_data = json.loads(row.attendees)
                            attendees_list = [
                                att.get('displayName', att.get('email', ''))
                                for att in attendees_data 
                                if att.get('displayName') or att.get('email')
                            ]
                        except:
                            pass
                    
                    events.append({
                        "id": row.id,
                        "type": "calendar_event",
                        "title": row.title,
                        "description": row.description or "",
                        "location": row.location or "",
                        "start_display": start_display,
                        "end_display": end_display,
                        "is_all_day": row.is_all_day,
                        "organizer_name": row.organizer_name or "",
                        "organizer_email": row.organizer_email or "",
                        "attendees": attendees_list,
                        "similarity": float(row.similarity)
                    })
                
                logger.info(f"Found {len(events)} calendar events with similarity > {self.similarity_threshold}")
                return events
                
        except Exception as e:
            logger.error(f"Failed to search calendar events: {str(e)}")
            return []
    
    async def get_context_for_query(self, query: str, user_id: str, max_results: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
        """Get relevant context for a user query using RAG"""
        try:
            # Generate embedding for the query
            query_embedding = await openai_service.generate_embedding(query)
            
            if not query_embedding:
                logger.warning("Failed to generate query embedding")
                return "", []
            
            # Check if this is a contact-specific query
            if self._is_contact_query(query):
                logger.info(f"Detected contact-specific query: {query}")
                return await self._handle_contact_query(query, query_embedding, user_id, max_results)
            
            # Check if this is a meeting invitation query
            if self._is_meeting_query(query):
                logger.info(f"Detected meeting invitation query: {query}")
                return await self._handle_meeting_query(query, query_embedding, user_id, max_results)
            
            # Check if this is a calendar/schedule query
            if self._is_calendar_query(query):
                logger.info(f"Detected calendar/schedule query: {query}")
                return await self._handle_calendar_query(query, query_embedding, user_id, max_results)
            
            # Search across all data types
            emails = await self.search_emails(query_embedding, user_id, limit=2)
            contacts = await self.search_contacts(query_embedding, user_id, limit=2)
            deals = await self.search_deals(query_embedding, user_id, limit=2)
            companies = await self.search_companies(query_embedding, user_id, limit=2)
            calendar_events = await self.search_calendar_events(query_embedding, user_id, limit=3)
            
            # Combine and sort by similarity
            all_results = emails + contacts + deals + companies + calendar_events
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
    
    def _is_contact_query(self, query: str) -> bool:
        """Detect if the query is specifically asking for contacts"""
        query_lower = query.lower()
        contact_keywords = [
            'list contacts', 'show contacts', 'my contacts', 'hubspot contacts',
            'list hubspot contacts', 'show me my contacts', 'who are my contacts',
            'all contacts', 'display contacts', 'get contacts', 'view contacts',
            'contacts list', 'contact list', 'list of contacts', 'show all contacts',
            'could you list', 'can you list', 'list out my', 'list my contacts'
        ]
        
        # Also check for individual keywords that strongly suggest contact queries
        strong_indicators = ['contacts', 'contact']
        query_words = query_lower.split()
        
        # Check for exact phrase matches first
        if any(keyword in query_lower for keyword in contact_keywords):
            return True
            
        # Check if query contains contact-related words and action words
        has_contact_word = any(indicator in query_words for indicator in strong_indicators)
        action_words = ['list', 'show', 'display', 'get', 'view', 'who', 'what']
        has_action_word = any(action in query_words for action in action_words)
        
        return has_contact_word and has_action_word
    
    def _is_meeting_query(self, query: str) -> bool:
        """Detect if the query is specifically asking for meeting invitations"""
        query_lower = query.lower()
        meeting_keywords = [
            'meeting invitations', 'meeting invitation', 'meeting invites', 'meeting invite',
            'calendar invitations', 'calendar invitation', 'calendar invites', 'calendar invite',
            'list meetings', 'show meetings', 'my meetings', 'pull meetings', 'pull meeting',
            'get meetings', 'get meeting invitations', 'list meeting invitations',
            'show meeting invitations', 'display meetings', 'view meetings'
        ]
        
        # Also check for individual keywords that strongly suggest meeting queries
        strong_indicators = ['meeting', 'meetings', 'invitation', 'invitations', 'invite', 'invites']
        query_words = query_lower.split()
        
        # Check for exact phrase matches first
        if any(keyword in query_lower for keyword in meeting_keywords):
            return True
            
        # Check if query contains meeting-related words and action words
        has_meeting_word = any(indicator in query_words for indicator in strong_indicators)
        action_words = ['list', 'show', 'display', 'get', 'view', 'pull', 'find']
        has_action_word = any(action in query_words for action in action_words)
        
        return has_meeting_word and has_action_word

    def _is_calendar_query(self, query: str) -> bool:
        """Detect if the query is specifically asking for calendar/schedule information"""
        query_lower = query.lower()
        calendar_keywords = [
            'schedule', 'calendar', 'appointments', 'events', 'next 24 hours',
            'next day', 'next week', 'today schedule', 'tomorrow schedule',
            'this week schedule', 'upcoming events', 'upcoming meetings',
            'what do i have', 'when am i free', 'when am i busy',
            'show my schedule', 'show my calendar', 'my agenda',
            'what\'s on my calendar', 'whats on my calendar'
        ]
        
        # Check for exact phrase matches first
        if any(keyword in query_lower for keyword in calendar_keywords):
            return True
            
        # Check for combinations of time + schedule words
        time_words = ['today', 'tomorrow', 'next', 'this', 'upcoming']
        schedule_words = ['schedule', 'calendar', 'events', 'meetings', 'agenda']
        
        query_words = query_lower.split()
        has_time_word = any(time_word in query_words for time_word in time_words)
        has_schedule_word = any(schedule_word in query_words for schedule_word in schedule_words)
        
        return has_time_word and has_schedule_word
    
    async def _handle_contact_query(self, query: str, query_embedding: List[float], user_id: str, max_results: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
        """Handle contact-specific queries by prioritizing contact results"""
        try:
            # Check if this is a "list all" type query
            query_lower = query.lower()
            list_all_keywords = ['list', 'all', 'show', 'display']
            
            if any(keyword in query_lower for keyword in list_all_keywords):
                # Get all contacts for list queries
                contacts = await self.get_all_contacts(user_id)
                logger.info(f"List query detected, retrieved {len(contacts)} total contacts")
            else:
                # Use semantic search for specific contact queries
                contacts = await self.search_contacts(query_embedding, user_id, limit=max_results)
                logger.info(f"Semantic search for contacts, found {len(contacts)} relevant contacts")
            
            # If we have contacts, prioritize them
            if contacts:
                # For list queries, show all contacts found (up to a reasonable limit)
                if any(keyword in query_lower for keyword in list_all_keywords):
                    # Show more contacts for list queries, limit to 10 to avoid overwhelming
                    top_results = contacts[:10]
                    # Add a few other relevant items if there's room
                    if len(top_results) < max_results:
                        remaining_slots = max_results - len(top_results)
                        emails = await self.search_emails(query_embedding, user_id, limit=min(2, remaining_slots))
                        top_results.extend(emails[:remaining_slots])
                else:
                    # For specific queries, use normal limits
                    remaining_slots = max(0, max_results - len(contacts))
                    
                    emails = await self.search_emails(query_embedding, user_id, limit=min(2, remaining_slots))
                    deals = await self.search_deals(query_embedding, user_id, limit=min(1, remaining_slots))
                    companies = await self.search_companies(query_embedding, user_id, limit=min(1, remaining_slots))
                    
                    # Combine with contacts first (higher priority)
                    all_results = contacts + emails + deals + companies
                    top_results = all_results[:max_results]
                
                logger.info(f"Contact query handled: {len([r for r in top_results if r['type'] == 'contact'])} contacts in {len(top_results)} total results")
            else:
                # No contacts found, fall back to regular search
                logger.info("No contacts found for contact query, falling back to regular search")
                emails = await self.search_emails(query_embedding, user_id, limit=3)
                deals = await self.search_deals(query_embedding, user_id, limit=2)
                companies = await self.search_companies(query_embedding, user_id, limit=2)
                
                all_results = emails + deals + companies
                all_results.sort(key=lambda x: x["similarity"], reverse=True)
                top_results = all_results[:max_results]
            
            # Build context string
            context = self._build_context_string(top_results)
            
            return context, top_results
            
        except Exception as e:
            logger.error(f"Failed to handle contact query: {str(e)}")
            return "", []
    
    def _format_date(self, date_string: str) -> str:
        """Format date string to readable format"""
        try:
            if not date_string:
                return "Date not available"
            
            # Handle both ISO format and datetime objects
            if isinstance(date_string, str):
                # Parse ISO format like "2025-07-05T07:03:56.261489"
                dt = datetime.fromisoformat(date_string.replace('Z', ''))
            else:
                dt = date_string
            
            # Format to "July 5, 2025"
            return dt.strftime("%B %d, %Y")
        except Exception:
            return date_string  # Return original if formatting fails

    def _build_context_string(self, results: List[Dict[str, Any]]) -> str:
        """Build a context string from search results"""
        if not results:
            return ""
        
        context_parts = []
        
        for item in results:
            if item["type"] == "email":
                formatted_date = self._format_date(item['received_at'])
                context_parts.append(
                    f"📧 Email from {item['sender']} - Subject: {item['subject']}\n"
                    f"Content: {item['content']}\n"
                    f"Date: {formatted_date}"
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
            elif item["type"] == "calendar_event":
                time_info = f"From {item['start_display']} to {item['end_display']}"
                location_info = f" at {item['location']}" if item['location'] else ""
                organizer_info = f" (Organized by {item['organizer_name']})" if item['organizer_name'] else ""
                attendees_info = f"\nAttendees: {', '.join(item['attendees'])}" if item['attendees'] else ""
                
                context_parts.append(
                    f"📅 Event: {item['title']}\n"
                    f"Time: {time_info}{location_info}{organizer_info}\n"
                    f"Description: {item['description'] or 'No description'}{attendees_info}"
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

    async def _handle_meeting_query(self, query: str, query_embedding: List[float], user_id: str, max_results: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
        """Handle meeting invitation queries by searching for meeting-related emails"""
        try:
            # For meeting queries, we want to return more results to be comprehensive
            meeting_limit = max(max_results, 10)  # Show at least 10 meeting invitations
            
            # First, try to get meeting emails using direct keyword search
            meeting_emails = await self.search_meeting_emails(user_id, limit=meeting_limit)
            
            if meeting_emails:
                logger.info(f"Found {len(meeting_emails)} meeting emails using direct search")
                # Build context from meeting emails
                context = self._build_context_string(meeting_emails)
                return context, meeting_emails
            else:
                # Fall back to semantic search with relaxed parameters
                logger.info("No meeting emails found with direct search, using semantic search")
                emails = await self.search_emails(query_embedding, user_id, limit=meeting_limit)
                
                # Filter for meeting-related emails
                meeting_related = []
                for email in emails:
                    subject = email.get('subject', '').lower()
                    content = email.get('content', '').lower()
                    
                    if any(keyword in subject or keyword in content for keyword in 
                           ['meeting', 'invitation', 'invite', 'calendar', 'scheduled', 'rsvp']):
                        meeting_related.append(email)
                
                if meeting_related:
                    context = self._build_context_string(meeting_related)
                    return context, meeting_related
                else:
                    # No meeting-related emails found
                    return "", []
                    
        except Exception as e:
            logger.error(f"Failed to handle meeting query: {str(e)}")
            return "", []
    
    async def search_meeting_emails(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for meeting-related emails using direct keyword matching"""
        try:
            async with AsyncSessionLocal() as session:
                # Search for emails with meeting-related keywords
                query = text("""
                    SELECT id, subject, content, sender, recipient, received_at
                    FROM emails 
                    WHERE user_id = :user_id 
                    AND (
                        LOWER(subject) LIKE '%meeting%' OR 
                        LOWER(subject) LIKE '%invitation%' OR 
                        LOWER(subject) LIKE '%invite%' OR 
                        LOWER(subject) LIKE '%calendar%' OR
                        LOWER(subject) LIKE '%scheduled%' OR
                        LOWER(subject) LIKE '%rsvp%' OR
                        LOWER(content) LIKE '%meeting%' OR
                        LOWER(content) LIKE '%invitation%' OR
                        LOWER(content) LIKE '%invite%' OR
                        LOWER(content) LIKE '%calendar%' OR
                        LOWER(content) LIKE '%scheduled%' OR
                        LOWER(content) LIKE '%rsvp%'
                    )
                    ORDER BY received_at DESC
                    LIMIT :limit
                """)
                
                result = await session.execute(query, {"user_id": user_id, "limit": limit})
                
                meetings = []
                for row in result:
                    meetings.append({
                        "id": row.id,
                        "type": "email",
                        "subject": row.subject,
                        "content": row.content[:500] if row.content else "",
                        "sender": row.sender,
                        "recipient": row.recipient,
                        "received_at": row.received_at.isoformat() if row.received_at else None,
                        "similarity": 1.0  # Set high similarity for direct matches
                    })
                
                logger.info(f"Found {len(meetings)} meeting emails using direct search")
                return meetings
                
        except Exception as e:
            logger.error(f"Failed to search meeting emails: {str(e)}")
            return []

    async def _handle_calendar_query(self, query: str, query_embedding: List[float], user_id: str, max_results: int = 5) -> Tuple[str, List[Dict[str, Any]]]:
        """Handle calendar/schedule queries by prioritizing calendar events"""
        try:
            # For calendar queries, we want to return more results to be comprehensive
            calendar_limit = max(max_results, 10)  # Show at least 10 calendar events
            
            # Search for calendar events
            calendar_events = await self.search_calendar_events(query_embedding, user_id, limit=calendar_limit)
            
            if calendar_events:
                logger.info(f"Found {len(calendar_events)} calendar events using semantic search")
                
                # Add some emails and contacts as additional context if there's room
                remaining_slots = max(0, max_results - len(calendar_events))
                additional_context = []
                
                if remaining_slots > 0:
                    emails = await self.search_emails(query_embedding, user_id, limit=min(2, remaining_slots))
                    additional_context.extend(emails)
                    
                    if len(additional_context) < remaining_slots:
                        contacts = await self.search_contacts(query_embedding, user_id, limit=min(1, remaining_slots - len(additional_context)))
                        additional_context.extend(contacts)
                
                # Combine calendar events with additional context
                all_results = calendar_events + additional_context
                top_results = all_results[:max_results] if max_results < len(all_results) else all_results
                
                context = self._build_context_string(top_results)
                return context, top_results
            else:
                # No calendar events found, fall back to regular search
                logger.info("No calendar events found for calendar query, falling back to regular search")
                emails = await self.search_emails(query_embedding, user_id, limit=3)
                contacts = await self.search_contacts(query_embedding, user_id, limit=2)
                
                all_results = emails + contacts
                all_results.sort(key=lambda x: x["similarity"], reverse=True)
                top_results = all_results[:max_results]
                
                context = self._build_context_string(top_results)
                return context, top_results
                
        except Exception as e:
            logger.error(f"Failed to handle calendar query: {str(e)}")
            return "", []
    
    async def get_all_contacts(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all HubSpot contacts for a user (used for list queries)"""
        try:
            async with AsyncSessionLocal() as session:
                # Get all contacts without similarity filtering
                result = await session.execute(
                    select(HubspotContact).where(HubspotContact.user_id == user_id)
                )
                
                contacts = []
                for contact in result.scalars().all():
                    name = f"{contact.firstname or ''} {contact.lastname or ''}".strip()
                    contacts.append({
                        "id": contact.id,
                        "type": "contact",
                        "name": name or "Unknown",
                        "email": contact.email,
                        "phone": contact.phone,
                        "company": contact.company,
                        "jobtitle": contact.jobtitle,
                        "industry": contact.industry,
                        "similarity": 1.0  # Set high similarity since these are direct matches
                    })
                
                logger.info(f"Retrieved {len(contacts)} total contacts for user {user_id}")
                return contacts
                
        except Exception as e:
            logger.error(f"Failed to get all contacts: {str(e)}")
            return []

# Global instance
rag_service = RAGService() 