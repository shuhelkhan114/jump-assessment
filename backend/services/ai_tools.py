"""
AI Tools for Function Calling
Comprehensive tool definitions for proactive AI agent functionality
"""
from typing import List, Dict, Any, Optional
import structlog
import json
from datetime import datetime, timedelta
from services.gmail_service import gmail_service
from services.hubspot_service import hubspot_service
from database import AsyncSessionLocal, HubspotContact, CalendarEvent
from sqlalchemy import select, func

logger = structlog.get_logger()

class AIToolsService:
    """Service for executing AI function calls"""
    
    def __init__(self):
        self.tools_registry = {}
        self._register_tools()
    
    def _register_tools(self):
        """Register all available tools"""
        self.tools_registry = {
            "search_contacts": self.search_contacts,
            "get_contact_details": self.get_contact_details,
            "create_contact": self.create_contact,
            "send_email": self.send_email,
            "get_calendar_availability": self.get_calendar_availability,
            "create_calendar_event": self.create_calendar_event,
            "add_hubspot_note": self.add_hubspot_note,
            "search_email_history": self.search_email_history,
            "get_time_suggestions": self.get_time_suggestions
        }
    
    async def execute_tool(self, tool_name: str, arguments: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Execute a tool with given arguments"""
        try:
            if tool_name not in self.tools_registry:
                return {"error": f"Unknown tool: {tool_name}"}
            
            # Add user_id to arguments for all tools
            arguments["user_id"] = user_id
            
            result = await self.tools_registry[tool_name](**arguments)
            logger.info(f"Executed tool {tool_name} successfully")
            return {"success": True, "result": result}
            
        except Exception as e:
            logger.error(f"Tool execution failed for {tool_name}: {str(e)}")
            return {"error": str(e)}
    
    async def search_contacts(self, query: str, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search for contacts in HubSpot and email history"""
        try:
            contacts = []
            
            async with AsyncSessionLocal() as session:
                # Search HubSpot contacts by name or email
                search_query = f"%{query.lower()}%"
                result = await session.execute(
                    select(HubspotContact).where(
                        HubspotContact.user_id == user_id
                    ).where(
                        func.lower(HubspotContact.firstname).like(search_query) |
                        func.lower(HubspotContact.lastname).like(search_query) |
                        func.lower(HubspotContact.email).like(search_query) |
                        func.lower(HubspotContact.company).like(search_query)
                    ).limit(limit)
                )
                
                hubspot_contacts = result.scalars().all()
                
                for contact in hubspot_contacts:
                    contacts.append({
                        "id": contact.id,
                        "source": "hubspot",
                        "name": f"{contact.firstname or ''} {contact.lastname or ''}".strip(),
                        "email": contact.email,
                        "company": contact.company,
                        "phone": contact.phone,
                        "confidence": self._calculate_confidence(query, contact)
                    })
            
            # Sort by confidence
            contacts.sort(key=lambda x: x["confidence"], reverse=True)
            return contacts
            
        except Exception as e:
            logger.error(f"Contact search failed: {str(e)}")
            return []
    
    def _calculate_confidence(self, query: str, contact) -> float:
        """Calculate confidence score for contact match"""
        query_lower = query.lower()
        confidence = 0.0
        
        # Exact name match
        full_name = f"{contact.firstname or ''} {contact.lastname or ''}".strip().lower()
        if query_lower == full_name:
            confidence += 1.0
        elif query_lower in full_name or full_name in query_lower:
            confidence += 0.8
        
        # Email match
        if contact.email and query_lower in contact.email.lower():
            confidence += 0.9
        
        # Company match
        if contact.company and query_lower in contact.company.lower():
            confidence += 0.6
        
        # Partial name matches
        for part in query_lower.split():
            if contact.firstname and part in contact.firstname.lower():
                confidence += 0.4
            if contact.lastname and part in contact.lastname.lower():
                confidence += 0.4
        
        return min(confidence, 1.0)
    
    async def get_contact_details(self, contact_id: str, user_id: str) -> Dict[str, Any]:
        """Get detailed information about a specific contact"""
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(HubspotContact).where(
                        HubspotContact.id == contact_id,
                        HubspotContact.user_id == user_id
                    )
                )
                contact = result.scalar_one_or_none()
                
                if not contact:
                    return {"error": "Contact not found"}
                
                return {
                    "id": contact.id,
                    "name": f"{contact.firstname or ''} {contact.lastname or ''}".strip(),
                    "email": contact.email,
                    "phone": contact.phone,
                    "company": contact.company,
                    "jobtitle": contact.jobtitle,
                    "industry": contact.industry,
                    "lifecycle_stage": contact.lifecyclestage,
                    "created_at": contact.created_at.isoformat() if contact.created_at else None
                }
                
        except Exception as e:
            logger.error(f"Get contact details failed: {str(e)}")
            return {"error": str(e)}
    
    async def create_contact(self, name: str, email: str, user_id: str, context: str = "customer") -> Dict[str, Any]:
        """Create a new HubSpot contact with specified context"""
        try:
            # Parse name into first and last name
            name_parts = name.strip().split()
            firstname = name_parts[0] if name_parts else ""
            lastname = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
            
            # Get user for HubSpot initialization
            from database import get_user_by_id
            user_data = await get_user_by_id(user_id)
            
            if not user_data or not user_data.get("hubspot_access_token"):
                return {"error": "HubSpot not connected or access token missing"}
            
            # Initialize HubSpot service
            initialized = hubspot_service.initialize_service(
                access_token=user_data["hubspot_access_token"]
            )
            
            if not initialized:
                return {"error": "Failed to initialize HubSpot service"}
            
            # Create contact data
            contact_data = {
                "email": email,
                "firstname": firstname,
                "lastname": lastname,
                "lifecyclestage": "lead" if context == "appointment_scheduling" else "customer"
            }
            
            # Create contact in HubSpot
            hubspot_contact = await hubspot_service.create_contact(contact_data)
            
            if not hubspot_contact:
                return {"error": "Failed to create contact in HubSpot"}
            
            # Save to local database with context
            async with AsyncSessionLocal() as session:
                new_contact = HubspotContact(
                    id=str(hubspot_contact.get("id")),
                    user_id=user_id,
                    hubspot_id=str(hubspot_contact.get("id")),
                    email=email,
                    firstname=firstname,
                    lastname=lastname,
                    lifecyclestage=contact_data["lifecyclestage"],
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                    # Set context and thank you email defaults based on context
                    contact_creation_context=context,
                    thank_you_email_sent=False if context == "customer" else True,  # Skip thank you for appointment contacts
                    thank_you_email_sent_at=datetime.utcnow() if context != "customer" else None
                )
                
                session.add(new_contact)
                await session.commit()
                
                logger.info(f"✅ Created contact {name} ({email}) with context '{context}'")
                
                return {
                    "success": True,
                    "contact_id": new_contact.id,
                    "hubspot_id": new_contact.hubspot_id,
                    "name": name,
                    "email": email,
                    "context": context
                }
                
        except Exception as e:
            logger.error(f"Create contact failed: {str(e)}")
            return {"error": str(e)}

    async def send_email(self, recipient_email: str, subject: str, body: str, user_id: str) -> Dict[str, Any]:
        """Send an email via Gmail"""
        try:
            # Get user for Gmail initialization
            from database import get_user_by_id
            user_data = await get_user_by_id(user_id)
            
            if not user_data or not user_data.get("google_access_token"):
                return {"error": "Gmail not connected or access token missing"}
            
            # Initialize Gmail service
            initialized = gmail_service.initialize_service(
                access_token=user_data["google_access_token"],
                refresh_token=user_data.get("google_refresh_token", ""),
                user_id=user_id
            )
            
            if not initialized:
                return {"error": "Failed to initialize Gmail service"}
            
            # Send email
            result = await gmail_service.send_email(
                to_email=recipient_email,
                subject=subject,
                body=body
            )
            
            if result:
                return {
                    "success": True,
                    "message_id": result.get("id"),
                    "recipient": recipient_email,
                    "subject": subject
                }
            else:
                return {"error": "Failed to send email"}
                
        except Exception as e:
            logger.error(f"Send email failed: {str(e)}")
            return {"error": str(e)}
    
    async def get_calendar_availability(self, start_date: str, end_date: str, user_id: str) -> Dict[str, Any]:
        """Get calendar availability for a date range"""
        try:
            from datetime import datetime
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            
            async with AsyncSessionLocal() as session:
                # Get existing calendar events in the range
                result = await session.execute(
                    select(CalendarEvent).where(
                        CalendarEvent.user_id == user_id,
                        CalendarEvent.start_datetime >= start_dt,
                        CalendarEvent.end_datetime <= end_dt
                    ).order_by(CalendarEvent.start_datetime)
                )
                
                events = result.scalars().all()
                
                busy_times = []
                for event in events:
                    busy_times.append({
                        "start": event.start_datetime.isoformat(),
                        "end": event.end_datetime.isoformat(),
                        "title": event.title
                    })
                
                return {
                    "available": True,
                    "busy_times": busy_times,
                    "period": {
                        "start": start_date,
                        "end": end_date
                    }
                }
                
        except Exception as e:
            logger.error(f"Get calendar availability failed: {str(e)}")
            return {"error": str(e)}
    
    async def get_time_suggestions(self, preferred_date: str, duration_minutes: int, user_id: str, 
                                 business_hours_start: str = "09:00", business_hours_end: str = "17:00", 
                                 next_24_hours: bool = False) -> List[Dict[str, Any]]:
        """Generate time slot suggestions based on calendar availability"""
        try:
            from datetime import datetime, timedelta
            
            suggestions = []
            
            if next_24_hours:
                # Generate availability for next 24 hours starting from current time
                now = datetime.utcnow()
                start_time = now + timedelta(hours=1)  # Start 1 hour from now
                end_time = start_time + timedelta(hours=24)  # Next 24 hours
                
                # Check availability for the entire 24-hour period
                availability = await self.get_calendar_availability(
                    start_time.isoformat(),
                    end_time.isoformat(),
                    user_id
                )
                
                busy_times = availability.get("busy_times", [])
                
                # Generate slots every 30 minutes within business hours of each day
                current_slot = start_time
                
                while current_slot + timedelta(minutes=duration_minutes) <= end_time:
                    # Only suggest slots during business hours (9 AM - 5 PM)
                    hour = current_slot.hour
                    if 9 <= hour < 17:  # Business hours
                        slot_end = current_slot + timedelta(minutes=duration_minutes)
                        
                        # Check if this slot conflicts with any busy time
                        is_available = True
                        for busy in busy_times:
                            busy_start = datetime.fromisoformat(busy["start"].replace('Z', '+00:00'))
                            busy_end = datetime.fromisoformat(busy["end"].replace('Z', '+00:00'))
                            
                            if (current_slot < busy_end and slot_end > busy_start):
                                is_available = False
                                break
                        
                        if is_available:
                            # Format time for display (remove explicit UTC formatting)
                            # Let the frontend handle timezone conversion
                            suggestions.append({
                                "start_time": current_slot.strftime("%I:%M %p"),
                                "date": current_slot.strftime("%A, %B %d"),
                                "start_datetime": current_slot.isoformat(),
                                "end_datetime": slot_end.isoformat(),
                                "available": True,
                                "formatted": f"{current_slot.strftime('%A, %B %d')} at {current_slot.strftime('%I:%M %p')}"
                            })
                        
                        # Limit to 6 suggestions for email readability
                        if len(suggestions) >= 6:
                            break
                    
                    # Move to next 30-minute slot
                    current_slot += timedelta(minutes=30)
                
            else:
                # Original single-day logic
                date_obj = datetime.fromisoformat(preferred_date.replace('Z', '+00:00')).date()
                
                # Generate potential time slots
                current_time = datetime.combine(date_obj, datetime.strptime(business_hours_start, "%H:%M").time())
                end_time = datetime.combine(date_obj, datetime.strptime(business_hours_end, "%H:%M").time())
                
                # Get busy times for the day
                day_start = datetime.combine(date_obj, datetime.min.time())
                day_end = datetime.combine(date_obj, datetime.max.time())
                
                availability = await self.get_calendar_availability(
                    day_start.isoformat(),
                    day_end.isoformat(),
                    user_id
                )
                
                busy_times = availability.get("busy_times", [])
                
                # Generate 30-minute slots and check availability
                while current_time + timedelta(minutes=duration_minutes) <= end_time:
                    slot_end = current_time + timedelta(minutes=duration_minutes)
                    
                    # Check if this slot conflicts with any busy time
                    is_available = True
                    for busy in busy_times:
                        busy_start = datetime.fromisoformat(busy["start"].replace('Z', '+00:00'))
                        busy_end = datetime.fromisoformat(busy["end"].replace('Z', '+00:00'))
                        
                        if (current_time < busy_end and slot_end > busy_start):
                            is_available = False
                            break
                    
                    if is_available:
                        suggestions.append({
                            "start_time": current_time.strftime("%H:%M"),
                            "end_time": slot_end.strftime("%H:%M"),
                            "start_datetime": current_time.isoformat(),
                            "end_datetime": slot_end.isoformat(),
                            "available": True
                        })
                    
                    # Move to next 30-minute slot
                    current_time += timedelta(minutes=30)
                    
                    # Limit to 5 suggestions
                    if len(suggestions) >= 5:
                        break
            
            return suggestions
            
        except Exception as e:
            logger.error(f"Get time suggestions failed: {str(e)}")
            return []
    
    async def create_calendar_event(self, title: str, start_datetime: str, end_datetime: str, 
                                   attendee_email: str, description: str, user_id: str) -> Dict[str, Any]:
        """Create a calendar event"""
        try:
            # Get user for calendar initialization
            from database import get_user_by_id
            user_data = await get_user_by_id(user_id)
            
            if not user_data or not user_data.get("google_access_token"):
                return {"error": "Google Calendar not connected"}
            
            # Initialize Gmail service (which includes calendar)
            initialized = gmail_service.initialize_service(
                access_token=user_data["google_access_token"],
                refresh_token=user_data.get("google_refresh_token", ""),
                user_id=user_id
            )
            
            if not initialized:
                return {"error": "Failed to initialize Google services"}
            
            # Create calendar event
            result = await gmail_service.create_calendar_event(
                title=title,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                description=description,
                attendees=[attendee_email],
                location=""
            )
            
            if result:
                return {
                    "success": True,
                    "event_id": result.get("id"),
                    "title": title,
                    "start": start_datetime,
                    "attendee": attendee_email
                }
            else:
                return {"error": "Failed to create calendar event"}
                
        except Exception as e:
            logger.error(f"Create calendar event failed: {str(e)}")
            return {"error": str(e)}
    
    async def add_hubspot_note(self, contact_id: str, note_content: str, user_id: str) -> Dict[str, Any]:
        """Add a note to a HubSpot contact"""
        try:
            # Get user for HubSpot initialization
            from database import get_user_by_id
            user_data = await get_user_by_id(user_id)
            
            if not user_data or not user_data.get("hubspot_access_token"):
                return {"error": "HubSpot not connected"}
            
            # Initialize HubSpot service
            initialized = hubspot_service.initialize_service(
                access_token=user_data["hubspot_access_token"]
            )
            
            if not initialized:
                return {"error": "Failed to initialize HubSpot service"}
            
            # Add note to contact
            note_data = {
                "engagement": {
                    "type": "NOTE"
                },
                "metadata": {
                    "body": note_content
                },
                "associations": {
                    "contactIds": [contact_id]
                }
            }
            
            result = await hubspot_service.create_engagement(note_data)
            
            if result:
                return {
                    "success": True,
                    "note_id": result.get("engagement", {}).get("id"),
                    "contact_id": contact_id,
                    "content": note_content
                }
            else:
                return {"error": "Failed to add note to HubSpot"}
                
        except Exception as e:
            logger.error(f"Add HubSpot note failed: {str(e)}")
            return {"error": str(e)}
    
    async def search_email_history(self, contact_email: str, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search email history with a specific contact"""
        try:
            from database import Email
            
            async with AsyncSessionLocal() as session:
                # Search emails with this contact
                result = await session.execute(
                    select(Email).where(
                        Email.user_id == user_id
                    ).where(
                        func.lower(Email.sender).like(f"%{contact_email.lower()}%") |
                        func.lower(Email.recipient).like(f"%{contact_email.lower()}%")
                    ).order_by(Email.received_at.desc()).limit(limit)
                )
                
                emails = result.scalars().all()
                
                email_history = []
                for email in emails:
                    email_history.append({
                        "id": email.id,
                        "subject": email.subject,
                        "sender": email.sender,
                        "recipient": email.recipient,
                        "received_at": email.received_at.isoformat() if email.received_at else None,
                        "content_preview": email.content[:200] if email.content else ""
                    })
                
                return email_history
                
        except Exception as e:
            logger.error(f"Search email history failed: {str(e)}")
            return []

# Tool definitions for OpenAI function calling
AI_TOOLS_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_contacts",
            "description": "Search for contacts by name, email, or company in HubSpot and email history",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (name, email, or company)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return",
                        "default": 5
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_contact_details",
            "description": "Get detailed information about a specific contact",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {
                        "type": "string",
                        "description": "The contact ID to get details for"
                    }
                },
                "required": ["contact_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_contact",
            "description": "Create a new HubSpot contact with specified context (customer or appointment_scheduling)",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Full name of the contact"
                    },
                    "email": {
                        "type": "string",
                        "description": "Email address of the contact"
                    },
                    "context": {
                        "type": "string",
                        "description": "Context of contact creation: 'customer' for regular customers, 'appointment_scheduling' for appointment contacts",
                        "enum": ["customer", "appointment_scheduling", "email_contact"],
                        "default": "customer"
                    }
                },
                "required": ["name", "email"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email via Gmail",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_email": {
                        "type": "string",
                        "description": "Email address of the recipient"
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line"
                    },
                    "body": {
                        "type": "string",
                        "description": "Email body content"
                    }
                },
                "required": ["recipient_email", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_time_suggestions",
            "description": "Get available time slot suggestions for a specific date or next 24 hours",
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred_date": {
                        "type": "string",
                        "description": "Preferred date in ISO format (YYYY-MM-DD) - ignored if next_24_hours is true"
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duration of the meeting in minutes",
                        "default": 60
                    },
                    "business_hours_start": {
                        "type": "string",
                        "description": "Start of business hours (HH:MM format)",
                        "default": "09:00"
                    },
                    "business_hours_end": {
                        "type": "string",
                        "description": "End of business hours (HH:MM format)",
                        "default": "17:00"
                    },
                    "next_24_hours": {
                        "type": "boolean",
                        "description": "Generate availability for the next 24 hours instead of a specific date",
                        "default": False
                    }
                },
                "required": ["preferred_date"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a calendar event",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Event title"
                    },
                    "start_datetime": {
                        "type": "string",
                        "description": "Start datetime in ISO format"
                    },
                    "end_datetime": {
                        "type": "string",
                        "description": "End datetime in ISO format"
                    },
                    "attendee_email": {
                        "type": "string",
                        "description": "Email of the attendee"
                    },
                    "description": {
                        "type": "string",
                        "description": "Event description",
                        "default": ""
                    }
                },
                "required": ["title", "start_datetime", "end_datetime", "attendee_email"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_hubspot_note",
            "description": "Add a note to a HubSpot contact",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {
                        "type": "string",
                        "description": "HubSpot contact ID"
                    },
                    "note_content": {
                        "type": "string",
                        "description": "Content of the note to add"
                    }
                },
                "required": ["contact_id", "note_content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_email_history",
            "description": "Search email history with a specific contact",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_email": {
                        "type": "string",
                        "description": "Email address to search communication history with"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of emails to return",
                        "default": 10
                    }
                },
                "required": ["contact_email"]
            }
        }
    }
]

# Global instance
ai_tools_service = AIToolsService() 